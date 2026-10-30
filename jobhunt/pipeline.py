"""`jobhunt fetch`: pull every source, store, discover companies, resolve their boards, score."""

from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import db, inbox, llm
from .core import CANCEL, Cancelled, Http, Job, check_cancel, company_key, load_profile, load_seed_companies, log
from .scoring import Scorer, refresh_company_stats, rescore_all
from .sources.ats import FETCHERS, resolve_ats
from .sources.boards import BOARDS
from .sources.linkedin import backfill, check_closed, linkedin


def store(conn: sqlite3.Connection, jobs: list[Job]) -> int:
    """Upsert postings and keep any company facts the source gave us. Returns how many are new."""
    new = 0
    for j in jobs:
        new += db.upsert_job(conn, j)
        if j.company_meta:
            m = j.company_meta
            cid = db.ensure_company(conn, j.company)
            conn.execute(
                """UPDATE companies SET startup = COALESCE(startup, ?), size = COALESCE(size, ?),
                     stage = COALESCE(NULLIF(stage, ''), ?), blurb = COALESCE(NULLIF(blurb, ''), ?) WHERE id = ?""",
                (int(bool(m.get("startup"))) if "startup" in m else None, m.get("size") or None,
                 m.get("stage") or None, m.get("blurb") or None, cid),
            )
    return new


def seed_companies(conn: sqlite3.Connection) -> int:
    seeds = load_seed_companies()
    for s in seeds:
        cid = db.ensure_company(conn, s["name"], kind=s.get("kind"), note=s.get("note"))
        conn.execute("UPDATE companies SET seeded = 1 WHERE id = ?", (cid,))
        if "startup" in s:
            conn.execute("UPDATE companies SET startup = ? WHERE id = ?", (int(bool(s["startup"])), cid))
        if s.get("ats") and s.get("slug"):
            conn.execute("UPDATE companies SET ats = ?, ats_slug = ?, ats_checked = ? WHERE id = ?",
                         (s["ats"], s["slug"], db.now(), cid))
    conn.commit()
    return len(seeds)


def resolve_companies(conn: sqlite3.Connection, http: Http, limit: int) -> int:
    """Find careers-board APIs for companies we don't have one for yet (retry after 30 days)."""
    rows = conn.execute(
        """SELECT id, name FROM companies
           WHERE ats IS NULL AND status != 'ignore'
             AND (ats_checked IS NULL OR ats_checked < date('now', '-30 day'))
           ORDER BY seeded DESC, fit_jobs DESC, eng_jobs DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    found = 0
    with ThreadPoolExecutor(8) as pool:
        futs = {pool.submit(resolve_ats, http, r["name"]): r for r in rows}
        for fut in as_completed(futs):
            r = futs[fut]
            try:
                hit = fut.result()
            except Exception as e:  # one bad company shouldn't stop the run
                log.debug("resolve %s failed: %s", r["name"], e)
                hit = None
            if hit:
                found += 1
                log.info("  board found: %s -> %s/%s", r["name"], *hit)
            conn.execute("UPDATE companies SET ats = ?, ats_slug = ?, ats_checked = ? WHERE id = ?",
                         (hit[0] if hit else None, hit[1] if hit else None, db.now(), r["id"]))
            conn.commit()
    return found


def _collect_ats(conn: sqlite3.Connection, http: Http) -> list[Job]:
    rows = conn.execute(
        "SELECT name, ats, ats_slug FROM companies WHERE ats IS NOT NULL AND status != 'ignore'"
    ).fetchall()
    jobs: list[Job] = []
    with ThreadPoolExecutor(8) as pool:
        futs = {pool.submit(lambda r=r: list(FETCHERS[r["ats"]](http, r["ats_slug"], r["name"]))): r for r in rows}
        for fut in as_completed(futs):
            try:
                jobs.extend(fut.result())
            except Exception as e:
                log.warning("  %s (%s) failed: %s", futs[fut]["name"], futs[fut]["ats"], e)
    return jobs


def _collect_boards(http: Http, profile: dict, only: set[str] | None) -> list[Job]:
    jobs: list[Job] = []
    with ThreadPoolExecutor(6) as pool:
        futs = {pool.submit(lambda f=f: list(f(http, profile))): name for name, f in BOARDS.items()
                if only is None or name in only}
        for fut in as_completed(futs):
            try:
                got = fut.result()
                log.info("  %-12s %4d postings", futs[fut], len(got))
                jobs.extend(got)
            except Exception as e:
                log.warning("  %s failed: %s", futs[fut], e)
    return jobs


def close_dead_linkedin(conn: sqlite3.Connection, http: Http, profile: dict) -> int:
    """Re-check LinkedIn postings still on your lists and close the ones that stopped taking applications.

    A posting is only closed when no other site has shown the same role in the last 3 days, since LinkedIn
    often stops taking applications while the company's own careers board still does.
    """
    budget = (profile.get("linkedin") or {}).get("max_closed_checks", 60)
    rows = conn.execute(
        """SELECT id, ext_id, dedup_key FROM jobs
           WHERE source = 'linkedin' AND status IN ('new', 'interested') AND rejected IS NULL AND score >= ?
             AND first_seen < date('now', 'localtime') AND COALESCE(checked_on, '') < date('now', '-2 day')
           ORDER BY score DESC LIMIT ?""", (profile.get("min_score", 40), budget)).fetchall()
    by_ext = {r["ext_id"]: r for r in rows}
    closed = 0
    for ext_id, is_closed in check_closed(http, list(by_ext)):
        r = by_ext[ext_id]
        conn.execute("UPDATE jobs SET checked_on = ? WHERE id = ?", (db.today(), r["id"]))
        open_elsewhere = conn.execute(
            """SELECT 1 FROM jobs WHERE dedup_key = ? AND source != 'linkedin'
                 AND last_seen >= date('now', '-3 day')""", (r["dedup_key"],)).fetchone()
        if is_closed and not open_elsewhere:
            db.set_job_status(conn, r["id"], "closed")
            closed += 1
        conn.commit()
    return closed


def assess_new(conn: sqlite3.Connection, profile: dict) -> int:
    """Have Claude assess the postings waiting on Today, best first, up to `auto_assess` per fetch."""
    limit = profile.get("auto_assess", 40)
    todo = [r for r in inbox.new_jobs(conn, 10_000) if not r["assessment"]][:limit]
    names = {r["id"]: f"{r['title']} · {r['company']}" for r in todo}
    done = iter(range(1, len(todo) + 1))
    count_lock = threading.Lock()
    log.info("  %d postings to assess", len(todo))

    def one(job_id: int) -> bool:
        if CANCEL.is_set():
            return False
        c = db.connect()  # one connection per thread
        try:
            a = llm.assess_job(c, job_id)
            with count_lock:
                n = next(done)
            log.info("  [%d/%d] %s: %s %s/10, %s", n, len(todo), names[job_id], a.get("verdict"), a.get("fit"),
                     a.get("summary", ""))
            return True
        except (llm.ClaudeError, OSError, subprocess.TimeoutExpired) as e:
            log.warning("  %s: assessment failed (%s), will retry next fetch", names[job_id], e)
            return False
        finally:
            c.close()

    with ThreadPoolExecutor(3) as pool:
        n = sum(pool.map(one, [r["id"] for r in todo]))
    check_cancel()  # assessments already running finish; the rest are skipped
    return n


class RunProgress(logging.Handler):
    """Copies the fetch's log into runs.progress so the dashboard can show it live, also for a fetch
    started from the terminal. A background thread writes it every couple of seconds, so logging never
    waits on the database while the fetch itself holds a write lock."""

    def __init__(self, run_id: int) -> None:
        super().__init__(logging.INFO)
        self.run_id, self.step, self.lines = run_id, "Starting", []
        self.state_lock, self.dirty, self.done = threading.Lock(), True, threading.Event()
        self.conn = sqlite3.connect(db.DB_PATH, timeout=2, check_same_thread=False)
        self.writer = threading.Thread(target=self._loop, daemon=True)
        self.writer.start()

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        with self.state_lock:
            if not msg.startswith(" "):  # top-level lines name the step; indented ones are its details
                self.step = msg.rstrip(".")
            self.lines = [*self.lines, {"t": time.strftime("%H:%M:%S"), "msg": msg.strip(),
                                        "level": record.levelname.lower(), "step": not msg.startswith(" ")}][-500:]
            self.dirty = True

    def _write(self) -> None:
        with self.state_lock:
            if not self.dirty:
                return
            data, self.dirty = json.dumps({"step": self.step, "lines": self.lines}), False
        try:
            self.conn.execute("UPDATE runs SET progress = ? WHERE id = ?", (data, self.run_id))
            self.conn.commit()
        except sqlite3.OperationalError:  # database busy: try again next tick, in a fresh transaction
            self.conn.rollback()
            self.dirty = True

    def _loop(self) -> None:
        while not self.done.wait(2):
            self._write()
            try:  # a cancel can come from the dashboard while this fetch runs in a terminal
                if self.conn.execute("SELECT cancel FROM runs WHERE id = ?", (self.run_id,)).fetchone()[0]:
                    CANCEL.set()
            except sqlite3.OperationalError:
                pass

    def close(self) -> None:
        if self.done.is_set():  # logging closes every handler again at exit
            return
        self.done.set()
        self.writer.join()
        self.conn.execute("PRAGMA busy_timeout = 30000")
        self._write()
        self.conn.close()
        super().close()


def fetch(sources: set[str] | None = None, resolve_limit: int = 60) -> dict:
    conn = db.connect()
    run_id = conn.execute("INSERT INTO runs (started) VALUES (?)", (db.now(),)).lastrowid
    conn.commit()
    progress = RunProgress(run_id)
    log.addHandler(progress)
    try:
        return _fetch(conn, run_id, sources, resolve_limit)
    except Cancelled:
        conn.rollback()
        log.info("Cancelled. Scoring what was found so far...")
        rescore_all(conn)
        refresh_company_stats(conn, load_profile().get("min_score", 40))
        summary = {"cancelled": True}
        conn.execute("UPDATE runs SET finished = ?, summary = ? WHERE id = ?", (db.now(), json.dumps(summary), run_id))
        conn.commit()
        log.info("Cancelled: postings found before the cancel are saved")
        return summary
    except Exception as e:
        log.error("Fetch failed: %s", e)
        raise
    finally:
        log.removeHandler(progress)
        progress.close()
        conn.close()


def _fetch(conn: sqlite3.Connection, run_id: int, sources: set[str] | None, resolve_limit: int) -> dict:
    http = Http()
    profile = load_profile()
    scorer = Scorer(profile)
    seed_companies(conn)
    want = lambda name: not sources or name in sources  # noqa: E731

    log.info("Job boards...")
    collected = _collect_boards(http, profile, {s for s in BOARDS if want(s)} if sources else None)
    new = store(conn, collected)
    conn.commit()

    if want("linkedin"):
        log.info("LinkedIn (public job pages, throttled)...")
        first_run = not conn.execute("SELECT 1 FROM jobs WHERE source = 'linkedin' LIMIT 1").fetchone()
        known = db.known_ext_ids(conn, "linkedin")

        def wants_detail(card: dict) -> bool:
            # Only spend detail fetches on cards that pass title/location rules.
            _, _, rejected = scorer.score({**card, "description": ""})
            return rejected is None

        n = 0
        for j in linkedin(http, profile, known=known, wants_detail=wants_detail, first_run=first_run):
            new += db.upsert_job(conn, j)
            conn.commit()  # don't hold the write lock across slow, throttled requests
            n += 1
        conn.commit()
        collected_n = n
        log.info("  linkedin     %4d postings", n)

        # Postings seen before without a description (e.g. budget ran out): read them now.
        missing = [r for r in conn.execute(
            """SELECT ext_id, company, title, location, remote FROM jobs
               WHERE source = 'linkedin' AND length(COALESCE(description, '')) < 200
                 AND last_seen >= date('now', '-14 day') AND seen = 0 AND status = 'new'
               ORDER BY last_seen DESC""").fetchall() if wants_detail(dict(r))]
        budget = (profile.get("linkedin") or {}).get("max_detail_fetches", 80)
        if missing:
            filled = 0
            for ext_id, desc in backfill(http, [r["ext_id"] for r in missing], budget):
                conn.execute("UPDATE jobs SET description = ? WHERE source = 'linkedin' AND ext_id = ?", (desc, ext_id))
                conn.commit()
                filled += 1
            log.info("  linkedin     %4d older postings filled in", filled)
        log.info("Checking LinkedIn postings on your lists still take applications...")
        closed = close_dead_linkedin(conn, http, profile)
        log.info("  linkedin     %4d postings no longer taking applications, closed", closed)
    else:
        collected_n = closed = 0

    # Every company that posts engineering roles has a dev team: remember it.
    for (name,) in conn.execute("SELECT DISTINCT company FROM jobs WHERE company != ''").fetchall():
        if not conn.execute("SELECT 1 FROM companies WHERE key = ?", (company_key(name),)).fetchone():
            db.ensure_company(conn, name)
    conn.commit()
    log.info("Scoring postings...")
    rescore_all(conn, scorer)
    refresh_company_stats(conn, profile.get("min_score", 40))

    if want("resolve"):
        log.info("Looking for careers boards (up to %d companies)...", resolve_limit)
        log.info("  %d new boards found", resolve_companies(conn, http, resolve_limit))

    if want("ats"):
        log.info("Company careers boards...")
        got = _collect_ats(conn, http)
        log.info("  %d engineering postings", len(got))
        new += store(conn, got)
        collected += got
        conn.commit()
    collected_total = len(collected) + collected_n

    if want("ats"):
        log.info("Scoring the careers-board postings...")
    rescore_all(conn, scorer)
    refresh_company_stats(conn, profile.get("min_score", 40))

    assessed = 0
    if want("assess") and profile.get("auto_assess", 40):
        log.info("Claude assessing new postings (up to %d)...", profile.get("auto_assess", 40))
        assessed = assess_new(conn, profile)
        log.info("  %d assessed", assessed)
    started = conn.execute("SELECT started FROM runs WHERE id = ?", (run_id,)).fetchone()[0]
    inbox_jobs = inbox.new_jobs(conn, 10_000)
    inbox_companies = inbox.new_companies(conn, 10_000)
    summary = {
        "collected": collected_total,
        "new": new,
        "closed": closed,
        "assessed": assessed,
        "new_fits": sum(1 for j in inbox_jobs if j["first_seen"] >= started),
        "new_companies": sum(1 for c in inbox_companies if (c["first_seen"] or "") >= started),
        "inbox_jobs": len(inbox_jobs),
        "inbox_companies": len(inbox_companies),
    }
    log.info("Done: %d postings checked, %d new fitting postings, %d new companies, %d assessed",
             collected_total, summary["new_fits"], summary["new_companies"], assessed)
    conn.execute("UPDATE runs SET finished = ?, summary = ? WHERE id = ?", (db.now(), json.dumps(summary), run_id))
    conn.commit()
    return summary
