"""The dashboard (http://127.0.0.1:5055, or your network with accounts). Claude steps run in background threads,
fetches in their own process; pages auto-refresh.

With accounts (users/), every page needs a login and runs as that user: core.as_user() is set for the request and
for each background task it starts, so all reads and writes go to that user's folder.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import threading
import time
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from urllib.parse import quote_plus

from flask import Flask, abort, g, jsonify, redirect, render_template, request, session, url_for
from markupsafe import Markup

from . import core, db, fields, i18n, inbox, llm, profile, salary
from .core import ROOT, as_user, countries, current_user, load_profile, multi_user

_pool = ThreadPoolExecutor(3)
_tasks: dict[str, str] = {}  # "user|key" -> "running" | "error: ..."
_procs: dict[str, subprocess.Popen] = {}  # user -> the fetch process the dashboard started for them
_lock = threading.Lock()


def _tkey(key: str) -> str:
    return f"{current_user() or ''}|{key}"


def _my_tasks() -> dict[str, str]:
    """This user's background tasks, by key ("cv", "assess:12"...)."""
    prefix = _tkey("")
    with _lock:
        return {k[len(prefix):]: v for k, v in _tasks.items() if k.startswith(prefix)}


def _run(key: str, fn, *args) -> None:
    user, key = current_user(), _tkey(key)
    with _lock:
        if _tasks.get(key) == "running":
            return
        _tasks[key] = "running"

    def work():
        with as_user(user):  # the task runs as whoever started it, in its own thread
            conn = db.connect()
            try:
                fn(conn, *args)
                with _lock:
                    _tasks.pop(key, None)
            except Exception as e:  # surfaced on the page
                traceback.print_exc()
                with _lock:
                    _tasks[key] = f"error: {e}"
            finally:
                conn.close()

    _pool.submit(work)


def _fetching() -> bool:
    proc = _procs.get(current_user() or "")
    return proc is not None and proc.poll() is None


def _start_fetch() -> None:
    """Run `jobhunt fetch` for you in its own process (like a fetch from the terminal): its threads can't mix
    users up, and it shows here through the runs table like any other fetch."""
    user = current_user() or ""
    with _lock:
        if _fetching():
            return
        env = {**os.environ, "JOBHUNT_USER": user} if user else dict(os.environ)
        log = open(core.data_dir() / "fetch.log", "a")  # noqa: SIM115
        proc = subprocess.Popen([sys.executable, "-m", "jobhunt.cli", "fetch"], cwd=ROOT, env=env,
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        proc.started_at = time.time()  # type: ignore[attr-defined]
        _procs[user] = proc
        log.close()


def _rescore_task(conn) -> None:
    from .scoring import refresh_company_stats, rescore_all

    rescore_all(conn)
    refresh_company_stats(conn, load_profile().get("min_score", 40))


def _split(text: str, sep: str = ",") -> list[str]:
    return [x.strip() for x in (text or "").replace("\r", "").split(sep) if x.strip()]


def _skills(text: str) -> dict[str, int]:
    """"python: 18" per line (or "python 18", or just "python" for 5 points)."""
    out = {}
    for line in _split(text, "\n"):
        name, _, pts = line.rpartition(":") if ":" in line else line.rpartition(" ")
        if not pts.strip().lstrip("-").isdigit():
            name, pts = line, "5"
        if name.strip():
            out[name.strip().lower()] = int(pts)
    return out


def _loads(s, default=None):
    if not s:
        return default
    try:
        return json.loads(s)
    except ValueError:
        return default


class Page:
    """One page of a list, from ?page=N (clamped to the pages that exist). Lists sharing a page each get
    their own `param`."""

    def __init__(self, items: list, per_page: int, param: str = "page") -> None:
        self.param = param
        self.total = len(items)
        self.pages = max(1, -(-self.total // per_page))
        self.page = min(max(request.args.get(param, 1, type=int), 1), self.pages)
        self.first = (self.page - 1) * per_page
        self.items = items[self.first:self.first + per_page]


INBOX_SORTS = {"score": "best score first", "newest": "newest first", "remote": "clear about remote first"}

def _level_matches(job, level: str) -> bool:
    """The seniority filter: "" any, "junior-mid", "senior", or "none" (posting doesn't say)."""
    return not level or (job["seniority"] or "none") == level


def _level_counts(jobs) -> Counter:
    """Postings per level, for the level dropdown: {"": all, "junior-mid": n, "senior": n, "none": n}."""
    counts = Counter(j["seniority"] or "none" for j in jobs)
    counts[""] = len(jobs)
    return counts


def _iso_date(s: str) -> str:
    """A YYYY-MM-DD date from a date input, or "" if it's empty or not a real date."""
    try:
        return date.fromisoformat(s.strip()).isoformat()
    except ValueError:
        return ""


def _page_url(pg: Page, page: int) -> str:
    """The current URL with only this list's page number changed, so filters, tabs and other lists are kept."""
    args = {**(request.view_args or {}), **request.args.to_dict(), pg.param: page}
    return url_for(request.endpoint, **args)


def _secret_key() -> str:
    path = core.USERS / ".secret_key"
    if not path.exists():
        path.write_text(secrets.token_hex(32))
        path.chmod(0o600)
    return path.read_text().strip()


def _lang() -> str:
    """The page language: your profile's, or before login the browser's."""
    if "lang" not in g:
        if multi_user() and not current_user():
            g.lang = request.accept_languages.best_match(["en", "pt"]) or "en"
        else:
            g.lang = load_profile()["language"]
    return g.lang


def _(text: str, **kw) -> Markup:
    """Translate interface text (see i18n.py). The text is trusted; values passed in are escaped. Without values,
    {placeholders} stay as they are (for the page's scripts to fill in)."""
    out = Markup(i18n.t(text, _lang()))
    return out.format(**kw) if kw else out


def _people_searches(name: str, p: dict) -> dict[str, str]:
    """LinkedIn people searches for the company page, by field: label -> keywords."""
    where = p["country"]
    if p["field"] == "psychology":
        return {
            "Clinical / technical director": f'"{name}" ("Diretor Clínico" OR "Diretora Clínica" OR "Diretor Técnico" '
                                             f'OR "Diretora Técnica")',
            "Psychology coordination": f'"{name}" (Coordenador OR Coordenadora) Psicologia',
            "HR / recruitment": f'"{name}" ("Recursos Humanos" OR Recrutamento OR "Talent Acquisition")',
            f"Psychologists ({where or 'anywhere'})": f'"{name}" Psicólogo {where}'.strip(),
        }
    role = {"fullstack": "full stack", "ml": "machine learning"}.get(p["roles"][0], p["roles"][0]) + " engineer"
    return {
        "CTO / Head of Engineering": f'"{name}" (CTO OR "Head of Engineering" OR "VP Engineering")',
        "Engineering managers": f'"{name}" "Engineering Manager"',
        "Tech recruiters": f'"{name}" ("Technical Recruiter" OR "Talent Acquisition")',
        f"Engineers ({where or 'anywhere'})": f'"{name}" {role} {where}'.strip(),
    }


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["TEMPLATES_AUTO_RELOAD"] = True  # template edits show on reload, no restart (set before jinja_env exists)
    app.jinja_env.filters["loads"] = _loads
    app.jinja_env.filters["q"] = quote_plus
    app.jinja_env.filters["reason"] = lambda r: i18n.reason(r, _lang())
    app.jinja_env.globals["_"] = _
    if multi_user():
        app.secret_key = _secret_key()
        app.config.update(SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True,
                          PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30)

    # ---------- who you are ----------

    @app.before_request
    def login_required():
        g.user_token = None
        if not multi_user() or request.endpoint in ("login", "login_post", "favicon", "static"):
            return None
        user = session.get("user")
        if not user or user not in core.accounts():
            session.clear()
            nxt = request.full_path if request.method == "GET" else "/"
            return redirect(url_for("login", next=nxt.rstrip("?")))
        g.user_token = core._USER.set(user)
        return None

    @app.teardown_request
    def forget_user(_exc):
        token = g.pop("user_token", None)
        if token is not None:
            core._USER.reset(token)

    @app.get("/login")
    def login():
        if not multi_user():
            return redirect("/")
        return render_template("login.html", error=request.args.get("error"), next=request.args.get("next", "/"))

    @app.post("/login")
    def login_post():
        name = request.form.get("user", "").strip().lower()
        nxt = request.form.get("next", "/")
        nxt = nxt if nxt.startswith("/") and not nxt.startswith("//") else "/"
        if not core.check_password(name, request.form.get("password", "")):
            time.sleep(1)  # slows down guessing
            return redirect(url_for("login", error=1, next=nxt))
        session.clear()
        session["user"] = name
        session.permanent = True
        return redirect(nxt)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.context_processor
    def globals_():
        if multi_user() and not current_user():  # the login page
            return {"lang": _lang(), "user": None, "multi_user": True}
        state = _fetch_state()
        tasks = _my_tasks()
        claude_running = sum(1 for k, v in tasks.items() if k not in ("fetch", "rescore") and v == "running")
        prof = load_profile()
        f = prof["field_def"]
        return {"home_city": prof["home_city"], "home_country": prof["country"], "has_profile": profile.exists(),
                "tasks": tasks, "fetching": state["running"], "fetch_step": state["step"],
                "fetch_cancelling": state["cancelling"], "lang": _lang(), "user": current_user(),
                "multi_user": multi_user(), "field": f, "words": f["words"], "field_name": prof["field"],
                "kinds_of_company": f["company_kinds"], "highlight_kind": f["highlight_kind"],
                "track_labels": f["track_labels"],
                "claude_running": claude_running, "JOB_STATUSES": db.JOB_STATUSES, "COMPANY_STATUSES": db.COMPANY_STATUSES,
                "TRIAGE_STATUSES": db.TRIAGE_STATUSES, "ACTIVE_STATUSES": db.ACTIVE_STATUSES,
                "CLOSED_STATUSES": db.CLOSED_STATUSES, "STATUS_LABELS": db.STATUS_LABELS, "page_url": _page_url,
                "applied_here": applied_here}

    def applied_here(j) -> list:
        """Your other applications at this posting's company (cached for the request)."""
        cache = g.setdefault("applied_here", {})
        key = (j["company_key"], j["dedup_key"])
        if key not in cache:
            cache[key] = db.applied_at_company(conn(), *key)
        return cache[key]

    def conn():
        if "db" not in g:
            g.db = db.connect()
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        c = g.pop("db", None)
        if c is not None:
            c.close()

    # Pages change as you triage, so the browser's back button must fetch them again, not show a stale copy.
    @app.after_request
    def no_cache(resp):
        if resp.mimetype == "text/html":
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.get("/favicon.svg")
    @app.get("/favicon.ico")  # browsers ask for this one on their own
    def favicon():
        return app.send_static_file("favicon.svg")

    @app.get("/")
    def home():
        return redirect(url_for("today"))

    # ---------- profile ----------

    @app.get("/profile")
    def profile_page():
        values = profile.editable()
        suggested = profile.draft()
        if suggested:
            values.update({k: v for k, v in suggested.items() if k != "location"})
            values["location"] = {**values["location"], **suggested.get("location", {})}
        cv = core.cv_text()
        return render_template("profile.html", p=values, suggested=suggested, roles=fields.get(values["field"])["roles"],
                               seniority_choices=profile.SENIORITY_CHOICES, field_choices=profile.FIELD_CHOICES,
                               language_choices=profile.LANGUAGE_CHOICES,
                               countries=sorted(core._COUNTRIES), cv_chars=len(cv),
                               cv_name=next((f.name for f in sorted(core.data_dir().glob("cv_upload.*"))), None),
                               saved=request.args.get("saved"), error=request.args.get("error"))

    @app.post("/profile")
    def profile_save():
        f = request.form
        profile.save({
            "field": profile.editable()["field"], "language": profile.editable()["language"],
            **{k: f.get(k, "").strip() for k in ("name", "email", "linkedin_url", "github_url", "story", "experience_note")},
            "experience_years": f.get("experience_years", 0, type=int),
            "roles": f.getlist("roles"),
            "skills": _skills(f.get("skills", "")),
            "must_have": [x.lower() for x in _split(f.get("must_have", ""))],
            "avoid": [x.lower() for x in _split(f.get("avoid", ""))],
            "languages": [x.lower() for x in _split(f.get("languages", ""))],
            "search_terms": _split(f.get("search_terms", ""), "\n"),
            "location": {"city": f.get("city", "").strip(), "nearby": [x.lower() for x in _split(f.get("nearby", ""))],
                         "country": f.get("country", ""), "remote": bool(f.get("remote")),
                         "onsite_elsewhere": [x.lower() for x in _split(f.get("onsite_elsewhere", ""))]},
            "exclude_companies": [x.lower() for x in _split(f.get("exclude_companies", ""))],
            "min_score": f.get("min_score", 40, type=int),
            "seniority": f.get("seniority") if f.get("seniority") in profile.SENIORITY_CHOICES else "any",
        })
        profile.discard_draft()
        _run("rescore", _rescore_task)  # every posting is ranked again against the new profile
        return redirect(url_for("profile_page", saved=1))

    @app.post("/profile/settings")
    def profile_settings():
        """Field and language: saved at once. A new field re-ranks everything with its job types and titles."""
        f = request.form
        current = profile.editable()
        changes = {}
        if f.get("field") in profile.FIELD_CHOICES and f["field"] != current["field"]:
            new = fields.get(f["field"])
            changes = {"field": f["field"], "roles": list(new["default_roles"]),
                       "language": current["language"] if profile.read().get("language") else new["default_language"]}
        if f.get("language") in profile.LANGUAGE_CHOICES:
            changes["language"] = f["language"]
        if changes:
            profile.save({**current, **changes})
            if "field" in changes:
                _run("rescore", _rescore_task)
        return redirect(url_for("profile_page"))

    @app.post("/profile/cv")
    def profile_cv():
        upload = request.files.get("cv")
        suffix = Path(upload.filename or "").suffix.lower() if upload else ""
        if suffix not in (".pdf", ".docx", ".txt", ".md", ".html", ".htm"):
            return redirect(url_for("profile_page", error="upload-type"))
        data = core.data_dir()
        incoming = data / f"cv_incoming{suffix}"  # the old CV stays until this one reads fine
        upload.save(incoming)
        try:
            text = profile.cv_to_text(incoming)
        except Exception:  # broken or password-protected file
            text = ""
        if len(text) < 200:
            incoming.unlink()
            return redirect(url_for("profile_page", error="upload-unreadable"))
        for old in data.glob("cv_upload.*"):
            old.unlink()
        incoming.rename(data / f"cv_upload{suffix}")
        profile.cv_text_path().write_text(text)
        core.cv_text.cache_clear()
        _run("cv", lambda conn: profile.from_cv(text))
        return redirect(url_for("profile_page"))

    @app.post("/profile/discard")
    def profile_discard():
        profile.discard_draft()
        return redirect(url_for("profile_page"))

    # ---------- today ----------

    @app.get("/today")
    def today():
        c = conn()
        min_score = load_profile().get("min_score", 40)
        last_run = c.execute("SELECT * FROM runs WHERE finished IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
        jobs_ = inbox.new_jobs(c)
        level = request.args.get("level", "")
        shown = [j for j in jobs_ if _level_matches(j, level)]
        sort = request.args.get("sort", "score")
        if sort not in INBOX_SORTS:
            sort = "score"
        if sort == "score":
            shown.sort(key=lambda j: j["first_seen"] or "", reverse=True)  # ties: newest first
            shown.sort(key=lambda j: j["score"] or 0, reverse=True)
        elif sort == "newest":
            shown.sort(key=lambda j: (j["posted_at"] or j["first_seen"] or "")[:10], reverse=True)
        # "remote": the inbox's own order (clear about remote first, then score)
        companies_ = inbox.new_companies(c)
        followups = c.execute(
            """SELECT o.*, co.name AS company FROM outreach o LEFT JOIN companies co ON co.id = o.company_id
               WHERE o.followup_on <= date('now', 'localtime') AND COALESCE(o.outcome, '') = ''
               ORDER BY o.followup_on""").fetchall()
        targets = c.execute(
            """SELECT * FROM companies WHERE status = 'target' AND id NOT IN
                 (SELECT company_id FROM outreach WHERE company_id IS NOT NULL) ORDER BY fit_jobs DESC""").fetchall()
        counts = {r["status"]: r["n"] for r in c.execute(
            """SELECT status, COUNT(DISTINCT dedup_key) n FROM jobs WHERE rejected IS NULL AND score >= ?
               GROUP BY status""", (min_score,))}
        sent = c.execute("SELECT COUNT(*) FROM outreach WHERE sent_on >= date('now', '-7 day')").fetchone()[0]
        kinds = {r["key"]: r for r in c.execute("SELECT key, id, kind, startup, stage FROM companies")}
        return render_template("today.html", jobs=jobs_, companies=companies_, followups=followups,
                               pg=Page(shown, 10), shown=shown, level=level, per_level=_level_counts(jobs_),
                               sort=sort, sorts=INBOX_SORTS,
                               cpg=Page(companies_, 10, "cpage"),
                               tpg=Page(targets, 10, "tpage"),
                               targets=targets, counts=counts, sent=sent, last_run=last_run, kinds=kinds,
                               ongoing=sum(counts.get(s, 0) for s in db.ACTIVE_STATUSES),
                               last_summary=_loads(last_run["summary"], {}) if last_run else {})

    @app.post("/inbox/seen")
    def inbox_seen():
        c = conn()
        inbox.mark_jobs_seen(c, [int(i) for i in request.form.getlist("job")])
        inbox.mark_companies_seen(c, [int(i) for i in request.form.getlist("company")])
        return redirect(request.referrer or url_for("today"))

    @app.post("/fetch")
    def fetch_now():
        _start_fetch()
        return redirect(url_for("fetch_page"))

    def _fetch_state() -> dict:
        """The latest fetch: running or not, its current step and log. Also covers terminal/scheduled fetches."""
        r = conn().execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        started_here = _procs.get(current_user() or "")
        if _fetching() and (r is None or r["finished"] or r["started"] < time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(started_here.started_at))):  # started, run row not written yet
            return {"running": True, "step": "Starting", "lines": [], "started": db.now(), "finished": None,
                    "failed": False, "cancelled": False, "cancelling": False}
        if r is None:
            return {"running": False, "step": "", "lines": [], "started": None, "finished": None, "failed": False,
                    "cancelled": False, "cancelling": False}
        p = _loads(r["progress"], {})
        lines = p.get("lines", [])
        failed = any(x["level"] == "error" for x in lines)
        # An unfinished run the dashboard started whose process is gone, or one older than 3 hours, crashed
        # without saying so.
        stale = conn().execute("SELECT ? < datetime('now', 'localtime', '-3 hour')", (r["started"],)).fetchone()[0]
        gone = started_here is not None and not _fetching()
        running = not r["finished"] and not failed and (_fetching() or not (stale or gone))
        return {"running": running, "step": p.get("step", "Starting"), "lines": lines, "started": r["started"],
                "finished": r["finished"], "failed": failed or (not r["finished"] and not running),
                "cancelled": bool(_loads(r["summary"], {}).get("cancelled")),
                "cancelling": running and bool(r["cancel"])}

    @app.post("/fetch/cancel")
    def fetch_cancel():
        c = conn()
        c.execute("UPDATE runs SET cancel = 1 WHERE finished IS NULL AND id = (SELECT MAX(id) FROM runs)")
        c.commit()  # the fetch process sees it within ~2 seconds (pipeline.RunProgress)
        return redirect(request.referrer or url_for("fetch_page"))

    @app.get("/fetch")
    def fetch_page():
        return render_template("fetch.html", run=_labelled(_fetch_state()))

    @app.get("/fetch/status")
    def fetch_status():
        return jsonify(_labelled(_fetch_state()))

    def _labelled(state: dict) -> dict:
        return {**state, "step_label": i18n.t(state["step"], _lang())}

    # ---------- jobs ----------

    @app.get("/jobs")
    def jobs():
        c = conn()
        status = request.args.get("status", "new")
        min_score = int(request.args.get("min", load_profile().get("min_score", 40)))
        q = request.args.get("q", "").strip()
        remote = request.args.get("remote", "")
        sql = """SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY dedup_key
                                    ORDER BY length(COALESCE(description,'')) DESC) rn,
                                COUNT(*) OVER (PARTITION BY dedup_key) n_sources
                                FROM jobs WHERE rejected IS NULL AND score >= ?
                                  AND company_key NOT IN (SELECT key FROM companies WHERE status = 'ignore'))
                 WHERE rn = 1"""
        params: list = [min_score]
        if status != "all":
            sql += " AND status = ?"
            params.append(status)
        if q:
            sql += " AND (title LIKE ? OR company LIKE ? OR description LIKE ?)"
            params += [f"%{q}%"] * 3
        if request.args.get("startup") == "1":
            sql += " AND company_key IN (SELECT key FROM companies WHERE startup = 1)"
        rcheck = request.args.get("rcheck", "")
        if rcheck in ("0", "1"):
            sql += " AND remote_check = ?"
            params.append(int(rcheck))
        if remote == "1":
            sql += " AND (remote = 1 OR lower(location) LIKE '%remote%')"
        elif remote == "0":
            sql += " AND COALESCE(remote, 0) = 0 AND lower(location) NOT LIKE '%remote%'"
        sql += " ORDER BY score DESC, first_seen DESC"
        country = request.args.get("country", "")
        level = request.args.get("level", "")
        # Country and level filter here, so each dropdown can count postings under every *other* filter.
        rows, per_country, per_level = [], Counter(), Counter()
        for r in c.execute(sql, params):
            cs = countries(r["location"], r["remote"])
            in_country, in_level = not country or country in cs, _level_matches(r, level)
            if in_level:
                per_country.update(cs)
            if in_country:
                per_level[r["seniority"] or "none"] += 1
                per_level[""] += 1
            if in_country and in_level:
                rows.append(r)
        kinds = {r["key"]: r for r in c.execute("SELECT key, id, kind, startup, stage FROM companies")}
        return render_template("jobs.html", pg=Page(rows, 20), status=status, min_score=min_score,
                               q=q, remote=remote, kinds=kinds, startup=request.args.get("startup", ""),
                               country=country, per_country=per_country.most_common(), rcheck=rcheck,
                               level=level, per_level=per_level)

    @app.get("/jobs/<int:job_id>")
    def job(job_id):
        c = conn()
        j = c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone() or abort(404)
        others = c.execute("SELECT id, source, url FROM jobs WHERE dedup_key = ? AND id != ?",
                           (j["dedup_key"], job_id)).fetchall()
        company = c.execute("SELECT * FROM companies WHERE key = ?", (j["company_key"],)).fetchone()
        # Another site's copy of the same role may state the salary when this one doesn't.
        copies = [j, *c.execute("SELECT salary, description FROM jobs WHERE dedup_key = ? AND id != ?",
                                (j["dedup_key"], job_id))]
        pay, from_desc = next((r for r in (salary.salary(x["salary"], x["description"]) for x in copies) if r[0]),
                              (None, False))
        return render_template("job.html", j=j, others=others, company=company, pay=pay, pay_from_desc=from_desc)

    @app.post("/jobs/<int:job_id>/status")
    def job_status(job_id):
        db.set_job_status(conn(), job_id, request.form["status"])
        nxt = request.form.get("next", "")  # the job page sends you back to the list; only local paths
        return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else request.referrer or url_for("jobs"))

    @app.post("/jobs/<int:job_id>/seen")
    def job_seen(job_id):
        inbox.mark_jobs_seen(conn(), [job_id])
        return redirect(request.referrer or url_for("job", job_id=job_id))

    # ---------- applications ----------

    @app.get("/applications")
    def applications():
        c = conn()
        db.expire_applications(c, load_profile().get("no_reply_after_days", 28))
        status = request.args.get("status", "")
        status = status if status in db.ACTIVE_STATUSES + db.CLOSED_STATUSES else ""
        # picking a status opens the tab it belongs to, whichever tab you picked it from
        tab = ("archive" if status in db.CLOSED_STATUSES else "ongoing") if status else (
            "archive" if request.args.get("tab") == "archive" else "ongoing")
        statuses = db.CLOSED_STATUSES if tab == "archive" else db.ACTIVE_STATUSES
        order = "closed_on DESC" if tab == "archive" else "applied_on DESC"
        q = request.args.get("q", "").strip()
        date_from, date_to = _iso_date(request.args.get("from", "")), _iso_date(request.args.get("to", ""))
        # The search matches role, company, location and your notes; the date range is the day you applied.
        # Tab and status counts follow both.
        conds, mparams = [], []
        if q:
            conds.append("(title LIKE ? OR company LIKE ? OR location LIKE ? OR notes LIKE ?)")
            mparams += [f"%{q}%"] * 4
        if date_from:
            conds.append("applied_on >= ?")
            mparams.append(date_from)
        if date_to:
            conds.append("applied_on <= ?")
            mparams.append(date_to)
        match = " AND ".join(conds) or "1"
        shown = [status] if status else statuses
        rows = c.execute(
            f"""SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY dedup_key
                                   ORDER BY length(COALESCE(description,'')) DESC) rn FROM jobs
                               WHERE status IN ({', '.join('?' * len(shown))}))
                WHERE rn = 1 AND {match} ORDER BY {order}, id DESC""", [*shown, *mparams]).fetchall()
        n = {s: k for s, k in c.execute(
            f"SELECT status, COUNT(DISTINCT dedup_key) FROM jobs WHERE {match} GROUP BY status", mparams)}
        return render_template("applications.html", pg=Page(rows, 20), tab=tab, q=q, today=db.today(),
                               status=status, per_status=n, date_from=date_from, date_to=date_to,
                               filtered=bool(q or status or date_from or date_to),
                               stats=db.applications_by_stack(c, [*load_profile()["field_def"]["tracks"],
                                                                     load_profile()["field_def"]["track_mixed"]]),
                               no_reply_days=load_profile().get("no_reply_after_days", 28),
                               n_ongoing=sum(n.get(s, 0) for s in db.ACTIVE_STATUSES),
                               n_archive=sum(n.get(s, 0) for s in db.CLOSED_STATUSES))

    @app.post("/jobs/<int:job_id>/notes")
    def job_notes(job_id):
        c = conn()
        c.execute("UPDATE jobs SET notes = ? WHERE id = ?", (request.form.get("notes", ""), job_id))
        c.commit()
        return redirect(url_for("job", job_id=job_id))

    @app.post("/jobs/<int:job_id>/assess")
    def job_assess(job_id):
        _run(f"assess:{job_id}", llm.assess_job, job_id)
        return redirect(url_for("job", job_id=job_id))

    @app.post("/jobs/<int:job_id>/draft")
    def job_draft(job_id):
        kind = request.form.get("kind", "")
        if kind in llm.JOB_MESSAGES:
            _run(f"draft:{job_id}:{kind}", llm.draft_for_job, job_id, [kind])
        else:
            _run(f"draft:{job_id}", llm.draft_for_job, job_id)
        return redirect(url_for("job", job_id=job_id))

    @app.post("/jobs/<int:job_id>/drafts")
    def job_drafts_save(job_id):
        """Your edits to drafted messages; the fields in the form replace the drafted ones."""
        c = conn()
        j = c.execute("SELECT drafts, dedup_key FROM jobs WHERE id = ?", (job_id,)).fetchone() or abort(404)
        keys = {k for kind in llm.JOB_MESSAGES.values() for k in kind}
        drafts = {**_loads(j["drafts"], {}), **{k: v.replace("\r\n", "\n") for k, v in request.form.items() if k in keys}}
        c.execute("UPDATE jobs SET drafts = ? WHERE dedup_key = ?", (json.dumps(drafts), j["dedup_key"]))
        c.commit()
        return redirect(url_for("job", job_id=job_id) + "#messages")

    # ---------- companies ----------

    @app.get("/companies")
    def companies():
        c = conn()
        kind = request.args.get("kind", "")
        status = request.args.get("status", "")
        q = request.args.get("q", "").strip()
        sql = "SELECT * FROM companies WHERE (eng_jobs > 0 OR seeded = 1)"
        params: list = []
        if kind == "startup":
            sql += " AND startup = 1"
        elif kind:
            sql += " AND kind = ?" if kind != "unknown" else " AND kind IS NULL"
            params += [kind] if kind != "unknown" else []
        if status:
            sql += " AND status = ?"
            params.append(status)
        else:
            sql += " AND status != 'ignore'"
        if q:
            sql += " AND name LIKE ?"
            params.append(f"%{q}%")
        sql += " ORDER BY fit_jobs DESC, best_score DESC, eng_jobs DESC"
        excluded = {s.lower() for s in load_profile().get("exclude_companies", [])}
        rows = [r for r in c.execute(sql, params).fetchall() if r["name"].lower() not in excluded]
        return render_template("companies.html", pg=Page(rows, 20), kind=kind, status=status, q=q)

    @app.get("/companies/<int:cid>")
    def company(cid):
        c = conn()
        co = c.execute("SELECT * FROM companies WHERE id = ?", (cid,)).fetchone() or abort(404)
        jobs_ = c.execute(
            """SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY dedup_key ORDER BY score DESC) rn
                              FROM jobs WHERE company_key = ?) WHERE rn = 1
               ORDER BY rejected IS NOT NULL, score DESC LIMIT 50""", (co["key"],)).fetchall()
        log_ = c.execute("SELECT * FROM outreach WHERE company_id = ? ORDER BY sent_on DESC", (cid,)).fetchall()
        searches = _people_searches(co["name"], load_profile())
        return render_template("company.html", co=co, jobs=jobs_, log=log_, searches=searches,
                               research=_loads(co["research"], {}), drafts=_loads(co["drafts"], {}),
                               today=db.today())

    @app.post("/companies/<int:cid>/drafts")
    def company_drafts_save(cid):
        """Your edits to the messages drafted for one person at this company."""
        c = conn()
        co = c.execute("SELECT drafts FROM companies WHERE id = ?", (cid,)).fetchone() or abort(404)
        drafts = _loads(co["drafts"], {})
        person = request.form.get("person", "")
        if person in drafts:
            drafts[person].update({k: request.form[k].replace("\r\n", "\n")
                                   for k in ("subject", "linkedin_note", "message", "followup") if k in request.form})
            c.execute("UPDATE companies SET drafts = ?, updated_at = ? WHERE id = ?", (json.dumps(drafts), db.now(), cid))
            c.commit()
        return redirect(url_for("company", cid=cid) + "#drafts")

    @app.post("/companies/<int:cid>/status")
    def company_status(cid):
        c = conn()
        s = request.form["status"]
        if s in db.COMPANY_STATUSES:
            c.execute("UPDATE companies SET status = ?, seen = 1, updated_at = ? WHERE id = ?", (s, db.now(), cid))
            c.commit()
        return redirect(request.referrer or url_for("companies"))

    @app.post("/companies/<int:cid>/kind")
    def company_kind(cid):
        c = conn()
        c.execute("UPDATE companies SET kind = ? WHERE id = ?", (request.form.get("kind") or None, cid))
        c.commit()
        return redirect(request.referrer or url_for("company", cid=cid))

    @app.post("/companies/<int:cid>/notes")
    def company_notes(cid):
        c = conn()
        c.execute("UPDATE companies SET notes = ? WHERE id = ?", (request.form.get("notes", ""), cid))
        c.commit()
        return redirect(url_for("company", cid=cid))

    @app.post("/companies/<int:cid>/research")
    def company_research(cid):
        _run(f"research:{cid}", llm.research_company, cid)
        return redirect(url_for("company", cid=cid))

    @app.post("/companies/<int:cid>/draft")
    def company_draft(cid):
        person = request.form.get("person", "").strip()
        _run(f"cdraft:{cid}", llm.draft_for_company, cid, person)
        return redirect(url_for("company", cid=cid))

    @app.post("/companies/<int:cid>/outreach")
    def company_outreach(cid):
        c = conn()
        f = request.form
        c.execute(
            "INSERT INTO outreach (company_id, person, channel, sent_on, followup_on, message) VALUES (?,?,?,?,?,?)",
            (cid, f.get("person"), f.get("channel"), f.get("sent_on") or db.today(), f.get("followup_on") or None,
             f.get("message")),
        )
        c.execute("UPDATE companies SET status = 'contacted', updated_at = ? WHERE id = ? AND status IN ('new','target')",
                  (db.now(), cid))
        c.commit()
        return redirect(url_for("company", cid=cid))

    @app.post("/outreach/<int:oid>")
    def outreach_update(oid):
        c = conn()
        f = request.form
        if f.get("outcome") is not None:
            c.execute("UPDATE outreach SET outcome = ? WHERE id = ?", (f["outcome"], oid))
            if f["outcome"] == "replied":
                c.execute("UPDATE companies SET status = 'replied' WHERE id = (SELECT company_id FROM outreach WHERE id = ?)", (oid,))
        if f.get("followup_on") is not None:
            c.execute("UPDATE outreach SET followup_on = ? WHERE id = ?", (f["followup_on"] or None, oid))
        c.commit()
        return redirect(request.referrer or url_for("today"))

    return app
