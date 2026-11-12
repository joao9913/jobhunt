# jobhunt

A local job-search tool. It collects postings from LinkedIn, company careers boards and job boards, ranks
them against your profile and CV, finds the companies hiring for roles like yours, researches the people who
hire there, and drafts messages that **you** send. It's built for software jobs and also works for
psychology (pick the field on the Profile page); the interface and everything Claude writes can be in English
or European Portuguese.

Everything runs on your computer. Nothing is sent automatically, nothing logs into LinkedIn, and your
profile, CV and job data never leave your machine (they're in `profile.yaml` and `data/`, or `users/` with
accounts, which git ignores).

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

1. Open **Profile**, pick your field and language, then upload your CV (PDF, Word, HTML, Markdown or text).
   Claude fills in the form in about a minute: job types, years of experience, skills, searches, where you live.
2. Check every field, fix what's off, and **Save profile**.
3. Press the green **Search** button. The first search takes 10–20 minutes; later ones are quicker.

## The profile

| Field | What it does |
|---|---|
| Language | English or Português (PT): the pages, and everything Claude writes for you (assessments, research, cover notes, messages). Saved as soon as you pick it. |
| Field | Software / tech or Psychology. Decides the job types below, which titles count, which sources are searched, the red flags and the words Claude uses (who to contact, what "the team" is). Changing it re-ranks everything. |
| Job types | Tech: backend, frontend, full stack, mobile, data, DevOps, ML, QA, embedded, security; titles of the types you don't tick are hidden. Psychology: clinical, education, work and organisations / HR, social, childhood, neuropsychology, forensic; the title must say psychologist, and one that only names types you didn't tick is hidden. |
| Searches | What's searched on LinkedIn and the job boards, one per line. |
| Experience (years) | Count real jobs in the field. Postings asking for more years rank lower; senior titles rank lower when you have under 3. |
| Seniority | Any level, hide senior postings, or only postings that say junior–mid (that one also hides postings that don't state a level). Uses the level badge: title words first (senior, lead, staff…), then the years of experience it asks for. |
| Skills and points | A posting gets the points for each skill it mentions. |
| Must mention one of | Postings that mention none of these (e.g. your main language) lose points. |
| Hide titles with | Tech you don't want, e.g. `java, php`. |
| Languages you speak | Postings that need another language lose points. |
| City, country, remote | Postings you can't do from home (on-site elsewhere, remote only for other regions) are hidden. Remote postings that don't say whether they hire from your country are flagged **check remote**. |
| Story | A few sentences in your own words. Claude's drafts never claim anything that isn't in your story or CV. |

Saving re-ranks every posting. You can also edit `profile.yaml` directly and run `uv run jobhunt score`.
Words are matched without accents, so "Psicóloga Clínica" matches `psicologa` and `clinica`.
Advanced settings in `profile.yaml` (all optional): `linkedin.max_detail_fetches` (no limit by default), `linkedin.searches` (to
set exact searches and locations), `wellfound.pages`, `no_reply_after_days` (default 28: an application with no answer by then becomes "no reply"), `cv_file_node` (a second CV that assessments and drafts use for Node/TypeScript postings), `auto_assess`, `llm_model`, `outreach_rules`, `red_flags`.

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
| `jobhunt serve [--host] [--install]` | The dashboard (on your network once there are accounts) |
| `jobhunt user add/passwd/list` | Accounts (see above) |
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
| LinkedIn | Public logged-out job pages, one request every 3–6 s. When LinkedIn rate-limits (it does now and then), it waits and retries instead of giving up, so a LinkedIn search can take an hour. Each run searches back to when the last complete one started, plus an hour (up to 30 days): fetch daily and it only asks for the last ~day; missed days leave no gap. Each search also re-checks postings on your lists and marks the ones that stopped taking applications as **closed by employer**. |
| Wellfound, YC jobs | Startup jobs with company size and funding stage. |
| Landing.jobs | Portugal tech board. |
| Himalayas, Remotive, RemoteOK, Arbeitnow | Remote and EU boards. |
| HN "Who is hiring" | Monthly thread, filtered to your main tech and location. |
| Net-Empregos | Portugal's biggest general job board (psychology field). Public search pages; a posting is only opened when its title and place already fit, a few seconds apart. Too many requests and the site shows a captcha for a few hours; the search then skips it and says so in the log. |

Tech profiles use every source above except Net-Empregos. Psychology profiles use LinkedIn, Net-Empregos and the
careers boards of companies you research.

`companies.yaml` is a starter list of companies to always watch, leaning towards Lisbon / Portugal and
EU-remote. Add or remove companies for your own search.

## Accounts: several people on one computer

With no accounts the app has one profile and the dashboard only listens on your computer. To let someone else
use it from their own computer on your home network, each with their own profile:

```sh
uv run jobhunt user add you --adopt   # your account; moves your profile.yaml and data/ into users/you/
uv run jobhunt user add ana           # another account, starting empty
uv run jobhunt serve                  # now asks for a login and listens on your network
```

`serve` prints the address to open from another computer (`http://<this computer's IP>:5055`). Each account
has its own folder, `users/<name>/` (profile, CV, database, optionally its own `companies.yaml`), and every page
and Claude task runs inside the folder of whoever is logged in. Nobody can see another account's data from the
dashboard. Whoever runs the computer can still read every folder.

- `uv run jobhunt user passwd ana` changes a password; `uv run jobhunt user list` lists accounts.
- `uv run jobhunt --user ana <command>` runs any command as that account (`fetch`, `score`, `assess`...).
- `uv run jobhunt fetch` with no `--user` searches for every account, one after the other; so does the daily
  schedule. Two searches never run at once, even when two people press **Search**: the second waits.
- `uv run jobhunt serve --install` keeps the dashboard running in the background, also after a restart (macOS).
  The computer has to be awake for others to reach it. The first time, macOS may ask whether Python can accept
  incoming connections: allow it.
- Claude runs on the subscription of whoever is logged in to Claude Code on this computer, for every account.
- The connection on your network is plain HTTP, like most home devices: fine at home, not on a shared network.

## Your data

- `profile.yaml`: your profile. `data/cv.txt`: your CV as text. `data/jobhunt.db`: postings, statuses, notes,
  outreach (SQLite). With accounts, the same files are in `users/<name>/`. All ignored by git.
- Delete `data/jobhunt.db` to start over with postings; your profile stays.

## Contributing

Changes go through pull requests: fork the repo (or push a branch, if you have access), open a pull request
against `main`, and it merges once the owner approves it. Keep personal data out of commits: `profile.yaml`
and `data/` are ignored by git; don't force-add them.
