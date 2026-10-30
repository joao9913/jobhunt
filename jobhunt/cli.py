"""Command line entry point: `jobhunt <command>`."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import textwrap

from . import db, llm
from .core import load_profile, log


def cmd_fetch(args) -> None:
    from .pipeline import fetch

    sources = set(args.only.split(",")) if args.only else None
    summary = fetch(sources, resolve_limit=args.resolve)
    print(f"\nDone: {summary['collected']} postings checked. Today: {summary['new_fits']} new fitting postings, "
          f"{summary['new_companies']} new companies. Inbox: {summary['inbox_jobs']} postings, "
          f"{summary['inbox_companies']} companies you haven't seen. Review with `jobhunt today` or `jobhunt serve`.")


def cmd_today(args) -> None:
    from . import inbox

    conn = db.connect()
    jobs = inbox.new_jobs(conn, args.n)
    companies = inbox.new_companies(conn, args.n)
    print(f"New postings ({len(jobs)})")
    for r in jobs:
        print(f"  {r['score']:3d}  #{r['id']:<6} {r['title'][:55]:55}  {r['company'][:25]:25}  {r['location'][:30]}")
    print(f"\nNew companies ({len(companies)})")
    for c in companies:
        tag = "startup" if c["startup"] else ("in-house tech" if c["kind"] == "non-tech" else (c["kind"] or ""))
        print(f"  #{c['id']:<6} {c['name'][:35]:35} {c['fit_jobs']:2d} fitting  {c['eng_jobs']:3d} eng  {tag}")
    if args.seen:
        inbox.mark_jobs_seen(conn, [r["id"] for r in jobs])
        inbox.mark_companies_seen(conn, [c["id"] for c in companies])
        print("\nMarked all of the above as seen.")


def cmd_score(args) -> None:
    from .scoring import refresh_company_stats, rescore_all

    conn = db.connect()
    n = rescore_all(conn)
    refresh_company_stats(conn, load_profile().get("min_score", 40))
    print(f"Rescored {n} postings.")


def cmd_top(args) -> None:
    conn = db.connect()
    for r in top_jobs(conn, args.n, status="new"):
        print(f"{r['score']:3d}  #{r['id']:<6} {r['title'][:55]:55}  {r['company'][:25]:25}  {r['location'][:30]}")


def top_jobs(conn, n: int, status: str | None = None, min_score: int | None = None):
    min_score = load_profile().get("min_score", 40) if min_score is None else min_score
    q = """SELECT * FROM (
             SELECT *, ROW_NUMBER() OVER (PARTITION BY dedup_key
                                          ORDER BY length(COALESCE(description,'')) DESC) AS rn
             FROM jobs WHERE rejected IS NULL AND score >= ?)
           WHERE rn = 1"""
    params: list = [min_score]
    if status:
        q += " AND status = ?"
        params.append(status)
    q += " ORDER BY score DESC, first_seen DESC LIMIT ?"
    params.append(n)
    return conn.execute(q, params).fetchall()


def cmd_assess(args) -> None:
    conn = db.connect()
    ids = args.ids or [r["id"] for r in top_jobs(conn, args.top, status="new") if not r["assessment"]]
    for i in ids:
        try:
            a = llm.assess_job(conn, i)
            print(f"#{i}: {a.get('verdict')} ({a.get('fit')}/10) {a.get('summary', '')}")
        except llm.ClaudeError as e:
            print(f"#{i}: failed: {e}", file=sys.stderr)


def cmd_research(args) -> None:
    conn = db.connect()
    for cid in _company_ids(conn, args.company):
        name = conn.execute("SELECT name FROM companies WHERE id = ?", (cid,)).fetchone()[0]
        print(f"Researching {name} (takes a minute or two)...")
        try:
            r = llm.research_company(conn, cid)
            print(textwrap.indent(json.dumps(r, indent=2, ensure_ascii=False), "  "))
        except llm.ClaudeError as e:
            print(f"  failed: {e}", file=sys.stderr)


def cmd_draft(args) -> None:
    conn = db.connect()
    if args.job:
        d = llm.draft_for_job(conn, args.job)
    else:
        (cid,) = _company_ids(conn, [args.company])
        d = llm.draft_for_company(conn, cid, args.person or "")
    for k, v in d.items():
        print(f"\n== {k} ==\n{v}")


def _company_ids(conn, refs: list[str]) -> list[int]:
    out = []
    for ref in refs:
        if ref.isdigit():
            out.append(int(ref))
            continue
        row = conn.execute("SELECT id FROM companies WHERE name LIKE ? ORDER BY eng_jobs DESC LIMIT 1",
                           (f"%{ref}%",)).fetchone()
        if not row:
            sys.exit(f"No company matching {ref!r}. Run `jobhunt fetch` first or add it to companies.yaml.")
        out.append(row["id"])
    return out


def cmd_serve(args) -> None:
    from .web import create_app

    print(f"Dashboard: http://127.0.0.1:{args.port}")
    create_app().run(host="127.0.0.1", port=args.port, debug=False, threaded=True)


def cmd_schedule(args) -> None:
    from .schedule import install

    print(install(args.hour))


def main() -> None:
    ap = argparse.ArgumentParser(prog="jobhunt", description="Find, rank and reach out to companies with dev teams.")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("fetch", help="collect postings from every source, discover companies, score")
    p.add_argument("--only", help="comma list: ats,resolve,linkedin,landingjobs,remotive,remoteok,arbeitnow,himalayas,hn")
    p.add_argument("--resolve", type=int, default=60, help="max companies to look up careers boards for")
    p.set_defaults(fn=cmd_fetch)

    p = sub.add_parser("today", help="what's new since you last looked (postings and companies)")
    p.add_argument("-n", type=int, default=100)
    p.add_argument("--seen", action="store_true", help="mark everything listed as seen afterwards")
    p.set_defaults(fn=cmd_today)

    sub.add_parser("score", help="re-rank everything after editing profile.yaml").set_defaults(fn=cmd_score)

    p = sub.add_parser("top", help="print the best unreviewed postings")
    p.add_argument("-n", type=int, default=30)
    p.set_defaults(fn=cmd_top)

    p = sub.add_parser("assess", help="ask Claude to triage postings (default: top 10 unassessed)")
    p.add_argument("ids", nargs="*", type=int)
    p.add_argument("--top", type=int, default=10)
    p.set_defaults(fn=cmd_assess)

    p = sub.add_parser("research", help="web research on companies: dev team, people, hooks")
    p.add_argument("company", nargs="+", help="company id or name")
    p.set_defaults(fn=cmd_research)

    p = sub.add_parser("draft", help="draft messages for a job or a company")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--job", type=int)
    g.add_argument("--company")
    p.add_argument("--person", help='e.g. "Ana Silva, Engineering Manager"')
    p.set_defaults(fn=cmd_draft)

    p = sub.add_parser("serve", help="open the local dashboard")
    p.add_argument("--port", type=int, default=5055)
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("schedule", help="run `fetch` every morning (macOS launchd)")
    p.add_argument("--hour", type=int, default=8)
    p.set_defaults(fn=cmd_schedule)

    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    log.setLevel(logging.DEBUG if args.verbose else logging.INFO)
    args.fn(args)


if __name__ == "__main__":
    main()
