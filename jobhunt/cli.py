"""Command line entry point: `jobhunt <command>`."""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import textwrap

from . import core, db, llm
from .core import load_profile, log


def cmd_fetch(args) -> None:
    from .pipeline import fetch

    if core.multi_user() and not core.current_user():
        # Every account, one after the other (the daily schedule runs this), each in its own process.
        failed = []
        for name in core.accounts():
            print(f"\n=== {name} ===", flush=True)
            cmd = [sys.executable, "-m", "jobhunt.cli", "--user", name, "fetch", *sys.argv[sys.argv.index("fetch") + 1:]]
            if subprocess.run(cmd, cwd=core.ROOT).returncode:
                failed.append(name)
        if failed:
            sys.exit(f"Fetch failed or was cancelled for: {', '.join(failed)}")
        return

    sources = set(args.only.split(",")) if args.only else None
    if sources and "netempregos" in sources:  # asked for by name: try it even if it was blocked recently
        from .sources.portugal import clear_block

        clear_block()
    summary = fetch(sources, resolve_limit=args.resolve)
    if summary.get("cancelled"):
        sys.exit("\nCancelled from the dashboard. Postings found before the cancel are saved.")
    print(f"\nDone: {summary['collected']} postings checked. Today: {summary['new_fits']} new fitting postings, "
          f"{summary['new_companies']} new companies, {summary['assessed']} assessed by Claude. Inbox: {summary['inbox_jobs']} postings, "
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


def _lan_ip() -> str | None:
    """This computer's address on your network (no packet is sent: connecting a UDP socket only picks a route)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.168.0.1", 9))
            return s.getsockname()[0]
    except OSError:
        return None


def cmd_serve(args) -> None:
    from .web import create_app

    host = args.host or ("0.0.0.0" if core.multi_user() else "127.0.0.1")
    if host != "127.0.0.1" and not core.multi_user():
        sys.exit("Without accounts the dashboard has no login, so it only listens on this computer. Add one with "
                 "`jobhunt user add NAME --adopt` first.")
    if args.install:
        from .schedule import install_server

        print(install_server(host, args.port))
        return
    print(f"Dashboard: http://127.0.0.1:{args.port}")
    if host == "0.0.0.0" and (ip := _lan_ip()):
        print(f"On your network: http://{ip}:{args.port}  (log in with an account from `jobhunt user list`)")
    create_app().run(host=host, port=args.port, debug=False, threaded=True)


def cmd_user(args) -> None:
    """Accounts: each gets users/<name>/ with its own profile, CV and database, and a password for the dashboard."""
    name = (args.name or "").lower()
    if args.action == "list":
        print("\n".join(core.accounts()) or "No accounts: the app runs with one profile and no login.")
        return
    if not core.USERNAME.match(name):
        sys.exit("A username is lowercase letters, digits, - or _ (up to 32), e.g. ana")
    exists = core.account_path(name).is_file()
    if args.action == "add" and exists:
        sys.exit(f"{name} already exists. Change the password with `jobhunt user passwd {name}`.")
    if args.action == "passwd" and not exists:
        sys.exit(f"No account called {name}.")
    if args.action == "add" and args.adopt:
        if core.accounts():
            sys.exit("--adopt is for the first account: it moves the existing profile.yaml and data/ into it.")
        if not (core.ROOT / "profile.yaml").exists() and not (core.ROOT / "data").exists():
            sys.exit("Nothing to adopt: no profile.yaml or data/ in the repo.")
    if sys.stdin.isatty():
        password = getpass.getpass(f"Password for {name}: ")
        if getpass.getpass("Again: ") != password:
            sys.exit("The passwords don't match.")
    else:
        password = sys.stdin.readline().rstrip("\n")
    if len(password) < 8:
        sys.exit("Use at least 8 characters.")
    core.set_password(name, password)
    if args.action == "passwd":
        print(f"Password changed for {name}.")
        return
    home = core.USERS / name
    if args.adopt:
        for item in ("profile.yaml", "data"):
            if (core.ROOT / item).exists():
                shutil.move(core.ROOT / item, home / item)
        print(f"Moved profile.yaml and data/ into {home}.")
    (home / "data").mkdir(exist_ok=True)
    print(f"Account {name} created ({home}). Start the dashboard with `jobhunt serve`; it now needs a login and "
          "listens on your network.")
    if not args.adopt and len(core.accounts()) == 1 and (core.ROOT / "profile.yaml").exists():
        print("Note: the existing profile.yaml and data/ in the repo aren't used with accounts. To keep them, "
              "remove this account's folder and run `jobhunt user add NAME --adopt` instead.")


def cmd_schedule(args) -> None:
    from .schedule import install

    print(install(args.hour))


def main() -> None:
    ap = argparse.ArgumentParser(prog="jobhunt", description="Find, rank and apply to jobs; research companies and "
                                                             "draft outreach.")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--user", help="the account to act as, when there are accounts (see `jobhunt user`)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("fetch", help="collect postings from every source, discover companies, score")
    p.add_argument("--only", help="comma list: ats,resolve,linkedin,landingjobs,remotive,remoteok,arbeitnow,himalayas,hn,"
                                  "netempregos,bep,assess")
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

    p = sub.add_parser("serve", help="open the dashboard")
    p.add_argument("--port", type=int, default=5055)
    p.add_argument("--host", help="address to listen on (default: 127.0.0.1, or 0.0.0.0 = your network with accounts)")
    p.add_argument("--install", action="store_true", help="keep it running in the background, also after a restart "
                                                          "(macOS launchd)")
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("user", help="accounts: add, passwd, list")
    p.add_argument("action", choices=["add", "passwd", "list"])
    p.add_argument("name", nargs="?")
    p.add_argument("--adopt", action="store_true", help="with add: move the existing profile.yaml and data/ into "
                                                        "this (first) account")
    p.set_defaults(fn=cmd_user)

    p = sub.add_parser("schedule", help="run `fetch` every morning (macOS launchd)")
    p.add_argument("--hour", type=int, default=8)
    p.set_defaults(fn=cmd_schedule)

    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    log.setLevel(logging.DEBUG if args.verbose else logging.INFO)
    if args.user:
        os.environ["JOBHUNT_USER"] = args.user.lower()
    if core.multi_user() and args.fn not in (cmd_user, cmd_serve, cmd_schedule, cmd_fetch) and not core.current_user():
        sys.exit(f"There are accounts: say which one, e.g. `jobhunt --user {(core.accounts() or ['NAME'])[0]} "
                 f"{args.cmd}`.")
    try:
        args.fn(args)
    except core.NoUser as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
