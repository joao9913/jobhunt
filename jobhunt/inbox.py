"""The daily inbox: postings and companies you haven't looked at yet.

A posting leaves the inbox for good once you set a status on it or mark it seen. "The same posting"
means same company + same normalised title, so a repost, a new ID or the same role on another site
doesn't bring it back. A company leaves once you set its status or mark it seen.
"""

from __future__ import annotations

import sqlite3

from .core import load_profile

# Postings that are new to you: no copy of this role was ever seen or given a status,
# and the company isn't ignored. Ones you can surely do from Lisbon come before ones to check.
NEW_JOBS = """
SELECT * FROM (
    SELECT j.*, ROW_NUMBER() OVER (PARTITION BY j.dedup_key ORDER BY length(COALESCE(j.description, '')) DESC) rn,
           COUNT(*) OVER (PARTITION BY j.dedup_key) n_sources
    FROM jobs j
    WHERE j.rejected IS NULL AND j.score >= :min
      AND j.dedup_key NOT IN (SELECT dedup_key FROM jobs WHERE seen = 1 OR status != 'new')
      AND j.company_key NOT IN (SELECT key FROM companies WHERE status = 'ignore')
) WHERE rn = 1
ORDER BY remote_check, score DESC, first_seen DESC
"""

# Companies new to you that are worth a look: they have roles that fit, or they're the kind you're
# targeting (startup / in-house tech team) and are hiring engineers.
NEW_COMPANIES = """
SELECT * FROM companies
WHERE seen = 0 AND status = 'new'
  AND (fit_jobs > 0 OR ((startup = 1 OR kind = 'non-tech') AND eng_jobs > 0))
ORDER BY fit_jobs DESC, (startup = 1 OR kind = 'non-tech') DESC, best_score DESC
"""


def _excluded() -> set[str]:
    return {s.lower() for s in load_profile().get("exclude_companies", [])}


def new_jobs(conn: sqlite3.Connection, limit: int = 200) -> list[sqlite3.Row]:
    excluded = _excluded()
    rows = conn.execute(NEW_JOBS + " LIMIT :limit",
                        {"min": load_profile().get("min_score", 40), "limit": limit}).fetchall()
    return [r for r in rows if r["company"].lower() not in excluded]


def new_companies(conn: sqlite3.Connection, limit: int = 200) -> list[sqlite3.Row]:
    excluded = _excluded()
    rows = conn.execute(NEW_COMPANIES + " LIMIT ?", (limit,)).fetchall()
    return [r for r in rows if r["name"].lower() not in excluded]


def counts(conn: sqlite3.Connection) -> tuple[int, int]:
    return len(new_jobs(conn, 10_000)), len(new_companies(conn, 10_000))


def mark_jobs_seen(conn: sqlite3.Connection, job_ids: list[int]) -> None:
    conn.executemany(
        "UPDATE jobs SET seen = 1 WHERE dedup_key = (SELECT dedup_key FROM jobs WHERE id = ?)",
        [(i,) for i in job_ids],
    )
    conn.commit()


def mark_companies_seen(conn: sqlite3.Connection, company_ids: list[int]) -> None:
    conn.executemany("UPDATE companies SET seen = 1 WHERE id = ?", [(i,) for i in company_ids])
    conn.commit()
