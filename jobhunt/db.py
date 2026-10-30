"""SQLite storage. One file in data/, no migrations framework: schema is created idempotently."""

from __future__ import annotations

import json
import sqlite3
import time

from .core import DATA, DB_PATH, Job, company_key, title_key

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            INTEGER PRIMARY KEY,
    source        TEXT NOT NULL,
    ext_id        TEXT NOT NULL,
    company       TEXT NOT NULL,
    company_key   TEXT NOT NULL,
    title         TEXT NOT NULL,
    dedup_key     TEXT NOT NULL,
    url           TEXT,
    location      TEXT,
    remote        INTEGER,
    description   TEXT,
    tags          TEXT,
    salary        TEXT,
    posted_at     TEXT,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    score         INTEGER,
    reasons       TEXT,
    rejected      TEXT,
    status        TEXT NOT NULL DEFAULT 'new',
    assessment    TEXT,
    drafts        TEXT,
    notes         TEXT,
    UNIQUE (source, ext_id)
);
CREATE INDEX IF NOT EXISTS jobs_dedup ON jobs (dedup_key);
CREATE INDEX IF NOT EXISTS jobs_company ON jobs (company_key);

CREATE TABLE IF NOT EXISTS companies (
    id            INTEGER PRIMARY KEY,
    key           TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    kind          TEXT,              -- tech | non-tech | NULL (unknown)
    seeded        INTEGER NOT NULL DEFAULT 0,
    note          TEXT,
    ats           TEXT,
    ats_slug      TEXT,
    ats_checked   TEXT,
    eng_jobs      INTEGER NOT NULL DEFAULT 0,
    fit_jobs      INTEGER NOT NULL DEFAULT 0,
    best_score    INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'new',   -- new | target | contacted | replied | ignore
    research      TEXT,
    drafts        TEXT,
    notes         TEXT,
    followup_on   TEXT,
    updated_at    TEXT
);

CREATE TABLE IF NOT EXISTS outreach (
    id            INTEGER PRIMARY KEY,
    company_id    INTEGER REFERENCES companies(id),
    job_id        INTEGER REFERENCES jobs(id),
    person        TEXT,
    channel       TEXT,
    sent_on       TEXT NOT NULL,
    followup_on   TEXT,
    message       TEXT,
    outcome       TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY,
    started       TEXT NOT NULL,
    finished      TEXT,
    summary       TEXT
);
"""

# Before applying | an ongoing application | how an application ended (it then moves to the archive).
TRIAGE_STATUSES = ["new", "interested", "ignored", "closed"]
ACTIVE_STATUSES = ["applied", "interviewing", "offer"]
CLOSED_STATUSES = ["rejected", "withdrawn", "no reply", "accepted", "declined"]
JOB_STATUSES = TRIAGE_STATUSES + ACTIVE_STATUSES + CLOSED_STATUSES
STATUS_LABELS = {"ignored": "not interested", "closed": "closed by employer", "rejected": "rejected by them", "withdrawn": "I withdrew",
                 "accepted": "offer accepted", "declined": "offer declined"}
COMPANY_STATUSES = ["new", "target", "contacted", "replied", "ignore"]


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def today() -> str:
    return time.strftime("%Y-%m-%d")


def connect() -> sqlite3.Connection:
    DATA.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=120, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    have = {r["name"] for r in conn.execute("PRAGMA table_info(companies)")}
    for col, decl in [("startup", "INTEGER"), ("size", "TEXT"), ("stage", "TEXT"), ("blurb", "TEXT"),
                      ("seen", "INTEGER NOT NULL DEFAULT 0"), ("first_seen", "TEXT")]:
        if col not in have:
            conn.execute(f"ALTER TABLE companies ADD COLUMN {col} {decl}")
    conn.execute("UPDATE companies SET first_seen = updated_at WHERE first_seen IS NULL")
    have = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
    for col, decl in [("seen", "INTEGER NOT NULL DEFAULT 0"), ("applied_on", "TEXT"), ("closed_on", "TEXT"),
                      ("checked_on", "TEXT"), ("remote_check", "INTEGER NOT NULL DEFAULT 0")]:  # checked_on: last time we checked it still takes applications
        if col not in have:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {decl}")
    conn.commit()


def set_job_status(conn: sqlite3.Connection, job_id: int, status: str) -> None:
    """Set a status on every copy of a posting. Keeps the date you applied and the date it closed."""
    if status not in JOB_STATUSES:
        return
    applied = status in ACTIVE_STATUSES or status in CLOSED_STATUSES
    conn.execute(
        """UPDATE jobs SET status = ?, seen = 1,
               applied_on = CASE WHEN ? THEN COALESCE(applied_on, ?) END,
               closed_on = CASE WHEN ? THEN COALESCE(closed_on, ?) END
           WHERE dedup_key = (SELECT dedup_key FROM jobs WHERE id = ?)""",
        (status, applied, today(), status in CLOSED_STATUSES, today(), job_id),
    )
    conn.commit()


def upsert_job(conn: sqlite3.Connection, job: Job) -> bool:
    """Insert or refresh a posting. Returns True if it is new."""
    ts = now()
    ckey = company_key(job.company)
    cur = conn.execute(
        "SELECT id, description FROM jobs WHERE source = ? AND ext_id = ?", (job.source, job.ext_id)
    )
    row = cur.fetchone()
    if row:
        desc = job.description if len(job.description or "") > len(row["description"] or "") else row["description"]
        conn.execute(
            """UPDATE jobs SET title=?, company=?, company_key=?, dedup_key=?, url=?, location=?, remote=?,
                   description=?, tags=?, salary=?, posted_at=COALESCE(?, posted_at), last_seen=?
               WHERE id=?""",
            (job.title, job.company, ckey, f"{ckey}|{title_key(job.title)}", job.url, job.location,
             _bool(job.remote), desc, json.dumps(job.tags), job.salary, job.posted_at, ts, row["id"]),
        )
        return False
    conn.execute(
        """INSERT INTO jobs (source, ext_id, company, company_key, title, dedup_key, url, location, remote,
                             description, tags, salary, posted_at, first_seen, last_seen)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (job.source, job.ext_id, job.company, ckey, job.title, f"{ckey}|{title_key(job.title)}", job.url,
         job.location, _bool(job.remote), job.description, json.dumps(job.tags), job.salary, job.posted_at,
         ts, ts),
    )
    return True


def ensure_company(conn: sqlite3.Connection, name: str, **fields) -> int:
    key = company_key(name)
    row = conn.execute("SELECT id FROM companies WHERE key = ?", (key,)).fetchone()
    if row:
        if fields:
            sets = ", ".join(f"{k} = COALESCE({k}, ?)" for k in fields)
            conn.execute(f"UPDATE companies SET {sets} WHERE id = ?", (*fields.values(), row["id"]))
        return row["id"]
    cols = ["key", "name", "updated_at", "first_seen", *fields]
    cur = conn.execute(
        f"INSERT INTO companies ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
        (key, name, now(), now(), *fields.values()),
    )
    return cur.lastrowid


def known_ext_ids(conn: sqlite3.Connection, source: str, with_description: bool = True) -> set[str]:
    q = "SELECT ext_id FROM jobs WHERE source = ?"
    if with_description:
        q += " AND length(COALESCE(description, '')) > 200"
    return {r[0] for r in conn.execute(q, (source,))}


def _bool(v: bool | None) -> int | None:
    return None if v is None else int(v)
