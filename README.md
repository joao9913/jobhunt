# jobhunt

A local job-search tool. It collects postings from LinkedIn, company careers boards and job boards, ranks
them against your profile and CV, finds companies with real in-house dev teams, researches the people who run
them, and drafts messages that **you** send.

Everything runs on your computer. Nothing is sent automatically, nothing logs into LinkedIn, and your
profile, CV and job data never leave your machine (they're in `profile.yaml` and `data/`, which git ignores).

## Setup

You need:

- [uv](https://docs.astral.sh/uv/) (`brew install uv`, or see their site)
- [Claude Code](https://claude.com/claude-code), logged in (`claude` in a terminal once). Assessments, CV
  reading, research and drafts run `claude -p` on your own Claude subscription; there's no API key.

Then:

```sh
git clone https://github.com/joao9913/jobhunt.git && cd jobhunt
uv run jobhunt serve        # dashboard at http://127.0.0.1:5055
```

1. Open **Profile**, upload your CV (PDF, Word, HTML, Markdown or text). Claude fills in the form in about a
   minute: job types, years of experience, skills, searches, where you live.
2. Check every field, fix what's off, and **Save profile**.
3. Press the green **Search** button. The first search takes 10–20 minutes; later ones are quicker.

## The profile

| Field | What it does |
|---|---|
| Job types | Backend, frontend, full stack, mobile, data, DevOps, ML, QA, embedded, security. Titles of the types you don't tick are hidden. |
| Searches | What's searched on LinkedIn and the job boards, one per line. |
| Experience (years) | Count real jobs in the field. Postings asking for more years rank lower; senior titles rank lower when you have under 3. |
| Skills and points | A posting gets the points for each skill it mentions. |
| Must mention one of | Postings that mention none of these (e.g. your main language) lose points. |
| Hide titles with | Tech you don't want, e.g. `java, php`. |
| Languages you speak | Postings that need another language lose points. |
| City, country, remote | Postings you can't do from home (on-site elsewhere, remote only for other regions) are hidden. Remote postings that don't say whether they hire from your country are flagged **check remote**. |
| Story | A few sentences in your own words. Claude's drafts never claim anything that isn't in your story or CV. |

Saving re-ranks every posting. You can also edit `profile.yaml` directly and run `uv run jobhunt score`.
Advanced settings in `profile.yaml` (all optional): `linkedin.max_detail_fetches`, `linkedin.searches` (to
set exact searches and locations), `wellfound.pages`, `auto_assess`, `llm_model`, `outreach_rules`, `red_flags`.

## Daily use

1. **Today** is your inbox: only postings and companies you haven't seen. Give a posting a status (or press
   **Seen**) and it never comes back, even when it's reposted or appears on another site.
2. **Jobs**: every ranked posting, filterable by country, level, remote and status. Open one to read Claude's
   take (most are assessed during the search), see the salary, **Draft messages**, then **Applied**.
3. **Applications**: what you've applied to, until it's closed; closed ones go to the Archive tab.
4. **Companies**: companies posting roles like yours. Open one → **Research with Claude** (dev-team
   evidence, stack, CTO / engineering managers / tech recruiters with sources) → **Draft** for a person →
   send it yourself → **Log it** with a follow-up date. Follow-ups show up on Today when due.

`uv run jobhunt schedule` runs the search every morning at 08:00 (macOS only).

## CLI

| Command | What it does |
|---|---|
| `jobhunt serve` | The dashboard |
| `jobhunt fetch [--only linkedin,ats,...]` | Search every source (same as the Search button) |
| `jobhunt today [--seen]` | Today's new postings and companies in the terminal |
| `jobhunt score` | Re-rank everything after editing `profile.yaml` |
| `jobhunt top -n 30` | Best unreviewed postings |
| `jobhunt assess [ids] [--top 10]` | Claude triage (apply / maybe / skip) |
| `jobhunt research "Company"` | Web research on a company |
| `jobhunt draft --job 123` / `--company X --person "Name, role"` | Draft messages |

Run them as `uv run jobhunt ...`.

## Where postings come from

| Source | Notes |
|---|---|
| Company careers boards | Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee, Personio public APIs, for the companies in `companies.yaml` and ones discovered from postings. |
| LinkedIn | Public logged-out job pages, throttled and capped. Each search also re-checks postings on your lists and marks the ones that stopped taking applications as **closed by employer**. |
| Wellfound, YC jobs | Startup jobs with company size and funding stage. |
| Landing.jobs | Portugal tech board. |
| Himalayas, Remotive, RemoteOK, Arbeitnow | Remote and EU boards. |
| HN "Who is hiring" | Monthly thread, filtered to your main tech and location. |

`companies.yaml` is a starter list of companies to always watch, leaning towards Lisbon / Portugal and
EU-remote. Add or remove companies for your own search.

## Your data

- `profile.yaml`: your profile. `data/cv.txt`: your CV as text. `data/jobhunt.db`: postings, statuses, notes,
  outreach (SQLite). All ignored by git.
- Delete `data/jobhunt.db` to start over with postings; your profile stays.

## Contributing

Changes go through pull requests: fork the repo (or push a branch, if you have access), open a pull request
against `main`, and it merges once the owner approves it. Keep personal data out of commits: `profile.yaml`
and `data/` are ignored by git; don't force-add them.
