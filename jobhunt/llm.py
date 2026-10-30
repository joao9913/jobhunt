"""Claude-powered steps, run through `claude -p` so they use your Claude subscription (no API key).

- assess:   is this posting worth applying to, and what's the angle?
- research: web research on a company: is there a real dev team, who leads it, who recruits for it.
- draft:    messages you send yourself (application note, LinkedIn note, cold message).
"""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess

from . import db
from .core import DATA, cv_text, load_profile, log


class ClaudeError(RuntimeError):
    pass


def run_claude(prompt: str, *, web: bool = False, timeout: int = 900) -> str:
    profile = load_profile()
    cmd = ["claude", "-p", "--output-format", "json", "--no-session-persistence", "--strict-mcp-config",
           "--model", profile.get("llm_model", "sonnet")]
    if web:
        cmd += ["--tools", "WebSearch,WebFetch", "--allowedTools", "WebSearch", "WebFetch",
                "--permission-mode", "dontAsk"]
    else:
        cmd += ["--tools", ""]
    # Run from data/ so no project CLAUDE.md or settings leak into the prompt.
    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=DATA)
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise ClaudeError((proc.stderr or proc.stdout)[:500]) from e
    if out.get("is_error"):
        raise ClaudeError(str(out.get("result"))[:500])
    return out.get("result", "")


def parse_json(text: str) -> dict:
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ClaudeError(f"Claude didn't return valid JSON: {text[:300]}") from e


def _me() -> str:
    p = load_profile()
    rules = "\n".join(f"- {r}" for r in p.get("outreach_rules", []))
    return f"""<candidate>
Name: {p['name']} · {p.get('linkedin_url', '')} · {p.get('github_url', '')}

CV:
{cv_text()}

Story (in their words):
{p.get('story', '')}

Experience, as they count it: {p.get('experience_years', 1)} year(s) of professional experience in the roles they want
({', '.join(p.get('roles', []))}).
{p.get('experience_note', '')}
</candidate>

<rules_for_anything_written_as_the_candidate>
{rules}
- Never invent facts, numbers or experience. Use only what's in the CV and story.
- No buzzwords ("passionate", "synergy", "rockstar"), no em-dash-heavy AI style. Plain, warm, direct.
</rules_for_anything_written_as_the_candidate>"""


def _job_block(job: sqlite3.Row) -> str:
    return f"""<job>
Company: {job['company']}
Title: {job['title']}
Location: {job['location']} {'(remote)' if job['remote'] else ''}
URL: {job['url']}
Description:
{(job['description'] or '(no description available)')[:12000]}
</job>"""


# ---------- assess ----------

ASSESS = """You are helping a job seeker triage postings. Be honest and practical: a "skip" saves them time.

{me}

{job}

Return ONLY a JSON object:
{{
  "fit": <integer 1-10, how strong a candidate they are for THIS role>,
  "verdict": "apply" | "maybe" | "skip",
  "summary": "one sentence on what the role really is",
  "why": ["2-4 concrete matches between the CV and the posting"],
  "gaps": ["real gaps or blockers: years, language, stack, location, visa"],
  "angle": "the one thing to lead with when applying",
  "company_type": "tech" | "non-tech with in-house dev team" | "agency/consultancy" | "unknown"
}}

Judge "years" against the experience they count above, not the CV's dates: a role asking for clearly more
is a real gap. If the company is a startup, weigh ownership and breadth (things they built or ran end to end)
as strengths; startups often care less about years and titles."""


def assess_job(conn: sqlite3.Connection, job_id: int) -> dict:
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    result = parse_json(run_claude(ASSESS.format(me=_me(), job=_job_block(job))))
    conn.execute("UPDATE jobs SET assessment = ? WHERE dedup_key = ?", (json.dumps(result), job["dedup_key"]))
    conn.commit()
    return result


# ---------- research ----------

RESEARCH = """Research this company for a job seeker who wants to reach out directly to its tech team.
Use web search and fetch pages. Only report what you actually found; put the source URL next to every
person and every non-obvious claim. Do NOT guess email addresses. If you can't find something, leave it empty.

Company: {name}
{hint}
Open engineering roles we know of: {roles}

Find:
1. What the company does, industry, size, where the tech team sits (presence in {where}? remote policy?).
2. Evidence of a real in-house dev team: engineering blog, GitHub org, tech talks, number of eng roles, stack.
3. Up to 6 people worth contacting, by public role: CTO / VP or Head of Engineering / Engineering managers
   (ideally for {roles_wanted}, ideally in {where}) / technical recruiters or talent acquisition for tech.
   Name, role, why them, and the public URL where you found them (LinkedIn, company site, talk, article).
4. One or two specific, recent things (product launch, migration, blog post, expansion) the candidate could
   mention to show genuine interest.

Return ONLY a JSON object:
{{
  "summary": "2-3 sentences",
  "industry": "...",
  "company_type": "tech" | "non-tech with in-house dev team" | "agency/consultancy" | "unknown",
  "is_startup": true | false,
  "stage": "e.g. Seed, Series A (2025, €12M), bootstrapped, public, or empty",
  "headcount": "approximate, with source, or empty",
  "local_presence": "what you found about them in {where}, or empty",
  "remote_policy": "...",
  "dev_team_evidence": [{{"what": "...", "url": "..."}}],
  "stack": ["..."],
  "careers_url": "...",
  "people": [{{"name": "...", "role": "...", "why": "...", "url": "..."}}],
  "hooks": [{{"what": "...", "url": "..."}}],
  "fit_note": "1-2 sentences: why this candidate specifically could be valuable to them"
}}

The candidate, for the fit note:
{cv}"""


def research_company(conn: sqlite3.Connection, company_id: int) -> dict:
    c = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
    roles = [r[0] for r in conn.execute(
        "SELECT DISTINCT title FROM jobs WHERE company_key = ? ORDER BY score DESC LIMIT 8", (c["key"],))]
    hint = f"Note: {c['note']}" if c["note"] else ""
    p = load_profile()
    prompt = RESEARCH.format(name=c["name"], hint=hint, roles=", ".join(roles) or "none known",
                             cv=cv_text()[:4000], where=p["country"] or p["home_city"],
                             roles_wanted=", ".join(p["roles"]))
    result = parse_json(run_claude(prompt, web=True))
    kind = {"tech": "tech", "non-tech with in-house dev team": "non-tech",
            "agency/consultancy": "agency"}.get(result.get("company_type", ""))
    startup = result.get("is_startup")
    conn.execute(
        """UPDATE companies SET research = ?, kind = COALESCE(?, kind), startup = COALESCE(?, startup),
             stage = COALESCE(NULLIF(?, ''), stage), updated_at = ? WHERE id = ?""",
        (json.dumps(result), kind, None if startup is None else int(bool(startup)), result.get("stage") or "",
         db.now(), company_id))
    if not c["ats"]:
        _adopt_board(conn, company_id, json.dumps(result))
    conn.commit()
    return result


BOARD_URLS = [
    ("greenhouse", r"(?:job-)?boards\.greenhouse\.io/([a-z0-9_-]+)"),
    ("lever", r"jobs\.(?:eu\.)?lever\.co/([a-z0-9_-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([a-z0-9_.-]+)"),
    ("recruitee", r"//([a-z0-9-]+)\.recruitee\.com"),
    ("workable", r"apply\.workable\.com/([a-z0-9_-]+)"),
    ("smartrecruiters", r"(?:jobs|careers)\.smartrecruiters\.com/([a-z0-9_-]+)"),
    ("personio", r"//([a-z0-9-]+)\.jobs\.personio\.(?:de|com)"),
]


def _adopt_board(conn: sqlite3.Connection, company_id: int, text: str) -> None:
    """If research found the company's careers board, start pulling it on every fetch."""
    from .core import Http
    from .sources.ats import _probe

    http = Http()
    for ats, rx in BOARD_URLS:
        for slug in dict.fromkeys(re.findall(rx, text.lower())):
            if _probe(http, ats, slug)[0]:
                conn.execute("UPDATE companies SET ats = ?, ats_slug = ?, ats_checked = ? WHERE id = ?",
                             (ats, slug, db.now(), company_id))
                log.info("Careers board found via research: %s/%s", ats, slug)
                return


# ---------- drafts ----------

DRAFT_JOB = """Write application messages for this candidate and this job. They will edit and send them
manually, so make them ready to send.

{me}

{job}

{assessment}

Return ONLY a JSON object:
{{
  "cover_note": "120-180 words for the application form / email. Lead with the angle. No 'Dear Sir/Madam'.",
  "linkedin_note_recruiter": "LinkedIn connection note to the recruiter for this role, max 280 characters.",
  "message_hiring_manager": "70-120 words to the engineering manager or tech lead: why this team, one proof point, a soft ask.",
  "subject": "email subject line"
}}"""

DRAFT_COMPANY = """Write cold outreach from this candidate to people at a company that has an in-house tech team.
There may be no open role that fits; the goal is a short conversation and being remembered when one opens.
They will edit and send these manually.

{me}

<company>
Name: {name}
Startup: {startup}
Research: {research}
Open engineering roles: {roles}
</company>

<person>{person}</person>

If it is a startup or small team, lead with ownership and range: the things in the CV and story they built,
shipped or ran end to end. Founders and early CTOs care about "can this person own things end to end", not titles.

Return ONLY a JSON object:
{{
  "linkedin_note": "connection request note, max 280 characters, specific to this person/company",
  "message": "80-140 words after they accept, or as an email: who I am, where I'm coming from, why THIS company's tech team (use a hook from the research), the ask (15 minutes, or who to talk to).",
  "followup": "40-70 words for a polite follow-up a week later, adding one new detail",
  "subject": "email subject line"
}}"""


def draft_for_job(conn: sqlite3.Connection, job_id: int) -> dict:
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assessment = f"<assessment>{job['assessment']}</assessment>" if job["assessment"] else ""
    result = parse_json(run_claude(DRAFT_JOB.format(me=_me(), job=_job_block(job), assessment=assessment)))
    conn.execute("UPDATE jobs SET drafts = ? WHERE dedup_key = ?", (json.dumps(result), job["dedup_key"]))
    conn.commit()
    return result


def draft_for_company(conn: sqlite3.Connection, company_id: int, person: str = "") -> dict:
    c = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
    roles = [r[0] for r in conn.execute(
        "SELECT DISTINCT title FROM jobs WHERE company_key = ? AND rejected IS NULL ORDER BY score DESC LIMIT 5",
        (c["key"],))]
    person = person or "Not specified: write for the CTO / Head of Engineering."
    result = parse_json(run_claude(DRAFT_COMPANY.format(
        me=_me(), name=c["name"], research=c["research"] or "(none yet)",
        startup=f"yes, {c['stage'] or 'stage unknown'}, {c['size'] or '?'} people" if c["startup"] else "no / unknown", roles=", ".join(roles) or "none",
        person=person)))
    drafts = json.loads(c["drafts"] or "{}")
    drafts[person] = result
    conn.execute("UPDATE companies SET drafts = ?, updated_at = ? WHERE id = ?",
                 (json.dumps(drafts), db.now(), company_id))
    conn.commit()
    log.info("Drafted outreach for %s (%s)", c["name"], person)
    return result
