# jobhunt

Private job-search pipeline: collect postings, rank them against your CV, find companies with real dev
teams, research the people who run those teams, and draft messages **you** send.

Nothing is ever sent automatically, and nothing logs into LinkedIn.

## Daily use

```sh
cd ~/dev/jobhunt
uv run jobhunt fetch        # ~5–15 min: all sources, new companies, careers boards, scoring
uv run jobhunt serve        # dashboard at http://127.0.0.1:5055
```

In the dashboard:

1. **Today** is your daily inbox: only postings and companies you haven't seen. Give a posting a status
   (or press **Seen**) and it never comes back, even if it's reposted or appears on another site.
   **Mark all as seen** clears the day. Follow-ups due and uncontacted targets are here too.
2. **Jobs**: ranked postings. Open one → **Assess fit** (Claude's honest take) → **Draft messages**
   (cover note, LinkedIn note for the recruiter, message for the hiring manager) → apply → set status.
3. **Companies**: every company posting engineering roles. Filter **in-house tech** for in-house tech
   businesses or **startups** for small teams. Open one → **Research with Claude** (dev-team evidence, stack, CTO / eng managers /
   tech recruiters with sources, things to mention) → **Draft** for a person → send it yourself on
   LinkedIn → **Log it** with a follow-up date. Follow-ups show up on Today when due.

Optional: `uv run jobhunt schedule` runs the fetch every morning at 08:00 (macOS launchd).

## CLI

| Command | What it does |
|---|---|
| `jobhunt fetch [--only linkedin,ats,...]` | Collect, discover, resolve careers boards, score |
| `jobhunt today [--seen]` | Today's new postings and companies in the terminal (`--seen` clears them) |
| `jobhunt score` | Re-rank everything after editing `profile.yaml` |
| `jobhunt top -n 30` | Best unreviewed postings in the terminal |
| `jobhunt assess [ids] [--top 10]` | Claude triage (apply / maybe / skip) |
| `jobhunt research "Mercedes-Benz.io"` | Web research on a company |
| `jobhunt draft --job 123` / `--company Sky --person "Ana Silva, EM"` | Draft messages |

## Where things come from

| Source | Notes |
|---|---|
| Company careers boards | Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee, Personio public APIs. Found automatically for seeded and discovered companies. |
| LinkedIn | Public logged-out job pages, throttled and capped (`profile.yaml → linkedin`). Stops on 429. Each fetch also re-checks up to `max_closed_checks` postings on your lists and moves the ones that stopped taking applications to **closed by employer**, unless another site still lists the role. |
| Wellfound | Startup jobs (Lisbon, Portugal, remote) with company size and funding stage. |
| YC job board | Y Combinator startups; mostly US, the location filter keeps the remote-friendly ones. |
| Landing.jobs | Portugal tech board. |
| Himalayas, Remotive, RemoteOK | Remote boards; Himalayas filtered to "open to Portugal". |
| Arbeitnow | EU board (mostly Germany; the location filter drops on-site roles). |
| HN "Who is hiring" | Monthly thread; keeps Python posts that are remote-EU or Portugal. |

## Tuning

- `profile.yaml`: titles to include/exclude, skill weights, red flags (5+ years, other languages),
  location rules, LinkedIn searches, your story for drafts. Run `jobhunt score` after editing.
- `companies.yaml`: companies to always watch. Add `ats`/`slug` if you know their careers board.
- On a company page you can correct its kind (in-house tech / tech / agency) or set it to `ignore`.

## Claude usage

Assess, research and draft run `claude -p` from `data/`, so they use your Claude subscription.
Assess and draft are small; research uses web search and is the heaviest, so run it on companies you
actually mean to contact. Everything Claude writes is limited to facts in your CV and `story`.

Data lives in `data/jobhunt.db` (SQLite). Delete it to start over.
