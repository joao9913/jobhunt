"""Local dashboard (http://127.0.0.1:5055). Claude steps run in background threads; pages auto-refresh."""

from __future__ import annotations

import json
import threading
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote_plus

from flask import Flask, abort, g, jsonify, redirect, render_template, request, url_for

from . import db, inbox, llm
from .core import CANCEL, countries, load_profile

_pool = ThreadPoolExecutor(3)
_tasks: dict[str, str] = {}  # key -> "running" | "error: ..."
_lock = threading.Lock()


def _run(key: str, fn, *args) -> None:
    with _lock:
        if _tasks.get(key) == "running":
            return
        _tasks[key] = "running"

    def work():
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


def _fetch_task(conn) -> None:
    from .pipeline import fetch

    fetch()


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


def _page_url(pg: Page, page: int) -> str:
    """The current URL with only this list's page number changed, so filters, tabs and other lists are kept."""
    args = {**(request.view_args or {}), **request.args.to_dict(), pg.param: page}
    return url_for(request.endpoint, **args)


def create_app() -> Flask:
    app = Flask(__name__)
    app.jinja_env.filters["loads"] = _loads
    app.jinja_env.filters["q"] = quote_plus

    @app.context_processor
    def globals_():
        state = _fetch_state()
        claude_running = sum(1 for k, v in _tasks.items() if k != "fetch" and v == "running")
        return {"tasks": dict(_tasks), "fetching": state["running"], "fetch_step": state["step"],
                "fetch_cancelling": state["cancelling"],
                "claude_running": claude_running, "JOB_STATUSES": db.JOB_STATUSES, "COMPANY_STATUSES": db.COMPANY_STATUSES,
                "TRIAGE_STATUSES": db.TRIAGE_STATUSES, "ACTIVE_STATUSES": db.ACTIVE_STATUSES,
                "CLOSED_STATUSES": db.CLOSED_STATUSES, "STATUS_LABELS": db.STATUS_LABELS, "page_url": _page_url}

    def conn():
        if "db" not in g:
            g.db = db.connect()
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        c = g.pop("db", None)
        if c is not None:
            c.close()

    @app.get("/")
    def home():
        return redirect(url_for("today"))

    # ---------- today ----------

    @app.get("/today")
    def today():
        c = conn()
        min_score = load_profile().get("min_score", 40)
        last_run = c.execute("SELECT * FROM runs WHERE finished IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
        jobs_ = inbox.new_jobs(c, 150)
        companies_ = inbox.new_companies(c, 60)
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
                               pg=Page(jobs_, 10),
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
        if _tasks.get("fetch") != "running":
            CANCEL.clear()  # here rather than in fetch(), so a cancel pressed before it really starts still counts
        _run("fetch", _fetch_task)
        return redirect(url_for("fetch_page"))

    def _fetch_state() -> dict:
        """The latest fetch: running or not, its current step and log. Also covers terminal/scheduled fetches."""
        r = conn().execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        if _tasks.get("fetch") == "running" and (r is None or r["finished"]):  # started, run row not written yet
            return {"running": True, "step": "Starting", "lines": [], "started": db.now(), "finished": None,
                    "failed": False, "cancelled": False, "cancelling": CANCEL.is_set()}
        if r is None:
            return {"running": False, "step": "", "lines": [], "started": None, "finished": None, "failed": False,
                    "cancelled": False, "cancelling": False}
        p = _loads(r["progress"], {})
        lines = p.get("lines", [])
        failed = _tasks.get("fetch", "").startswith("error") or any(x["level"] == "error" for x in lines)
        # An unfinished run older than 3 hours crashed without saying so.
        stale = conn().execute("SELECT ? < datetime('now', 'localtime', '-3 hour')", (r["started"],)).fetchone()[0]
        running = not r["finished"] and not failed and (_tasks.get("fetch") == "running" or not stale)
        return {"running": running, "step": p.get("step", "Starting"), "lines": lines, "started": r["started"],
                "finished": r["finished"], "failed": failed or (not r["finished"] and not running),
                "cancelled": bool(_loads(r["summary"], {}).get("cancelled")),
                "cancelling": running and bool(r["cancel"])}

    @app.post("/fetch/cancel")
    def fetch_cancel():
        c = conn()
        c.execute("UPDATE runs SET cancel = 1 WHERE finished IS NULL AND id = (SELECT MAX(id) FROM runs)")
        c.commit()
        if _tasks.get("fetch") == "running":
            CANCEL.set()  # running in this process: stop now instead of on the next progress poll
        return redirect(request.referrer or url_for("fetch_page"))

    @app.get("/fetch")
    def fetch_page():
        return render_template("fetch.html", run=_fetch_state())

    @app.get("/fetch/status")
    def fetch_status():
        return jsonify(_fetch_state())

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
        # Location is free text, so the country filter runs here; the counts cover every other filter.
        rows, per_country = [], Counter()
        for r in c.execute(sql, params):
            cs = countries(r["location"], r["remote"])
            per_country.update(cs)
            if not country or country in cs:
                rows.append(r)
        kinds = {r["key"]: r for r in c.execute("SELECT key, id, kind, startup, stage FROM companies")}
        return render_template("jobs.html", pg=Page(rows, 20), status=status, min_score=min_score,
                               q=q, remote=remote, kinds=kinds, startup=request.args.get("startup", ""),
                               country=country, per_country=per_country.most_common(), rcheck=rcheck)

    @app.get("/jobs/<int:job_id>")
    def job(job_id):
        c = conn()
        j = c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone() or abort(404)
        others = c.execute("SELECT id, source, url FROM jobs WHERE dedup_key = ? AND id != ?",
                           (j["dedup_key"], job_id)).fetchall()
        company = c.execute("SELECT * FROM companies WHERE key = ?", (j["company_key"],)).fetchone()
        return render_template("job.html", j=j, others=others, company=company)

    @app.post("/jobs/<int:job_id>/status")
    def job_status(job_id):
        db.set_job_status(conn(), job_id, request.form["status"])
        return redirect(request.referrer or url_for("jobs"))

    @app.post("/jobs/<int:job_id>/seen")
    def job_seen(job_id):
        inbox.mark_jobs_seen(conn(), [job_id])
        return redirect(request.referrer or url_for("job", job_id=job_id))

    # ---------- applications ----------

    @app.get("/applications")
    def applications():
        c = conn()
        tab = "archive" if request.args.get("tab") == "archive" else "ongoing"
        statuses = db.CLOSED_STATUSES if tab == "archive" else db.ACTIVE_STATUSES
        order = "closed_on DESC" if tab == "archive" else "applied_on DESC"
        rows = c.execute(
            f"""SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY dedup_key
                                   ORDER BY length(COALESCE(description,'')) DESC) rn FROM jobs
                               WHERE status IN ({', '.join('?' * len(statuses))}))
                WHERE rn = 1 ORDER BY {order}, id DESC""", statuses).fetchall()
        n = {s: k for s, k in c.execute("SELECT status, COUNT(DISTINCT dedup_key) FROM jobs GROUP BY status")}
        return render_template("applications.html", pg=Page(rows, 20), tab=tab, today=db.today(),
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
        _run(f"draft:{job_id}", llm.draft_for_job, job_id)
        return redirect(url_for("job", job_id=job_id))

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
        name = co["name"]
        searches = {
            "CTO / Head of Engineering": f'"{name}" (CTO OR "Head of Engineering" OR "VP Engineering")',
            "Engineering managers": f'"{name}" "Engineering Manager"',
            "Tech recruiters": f'"{name}" ("Technical Recruiter" OR "Talent Acquisition")',
            "Backend engineers (in Portugal)": f'"{name}" backend engineer Portugal',
        }
        return render_template("company.html", co=co, jobs=jobs_, log=log_, searches=searches,
                               research=_loads(co["research"], {}), drafts=_loads(co["drafts"], {}),
                               today=db.today())

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
