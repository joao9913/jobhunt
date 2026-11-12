"""Claude-powered steps, run through `claude -p` so they use your Claude subscription (no API key).

- assess:   is this posting worth applying to, and what's the angle?
- research: web research on a company: is there a real dev team, who leads it, who recruits for it.
- draft:    messages you send yourself (application note, LinkedIn note, cold message).
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

from . import db
from .core import cv_text, data_dir, load_profile, log


class ClaudeError(RuntimeError):
    pass


# Where Claude Code installs itself. A dashboard or daily search started by launchd gets a minimal PATH
# (/usr/bin:/bin...) that has none of these, so look here too.
CLAUDE_PLACES = ["~/.local/bin/claude", "~/.claude/local/claude", "/opt/homebrew/bin/claude", "/usr/local/bin/claude"]


def claude_bin() -> str:
    found = shutil.which("claude") or next(
        (str(p) for p in (Path(x).expanduser() for x in CLAUDE_PLACES) if p.is_file()), None)
    if not found:
        raise ClaudeError("Claude Code isn't installed on this computer (no `claude` command). Install it from "
                          "https://claude.com/claude-code and log in once by running `claude` in a terminal.")
    return found


def run_claude(prompt: str, *, web: bool = False, timeout: int = 900) -> str:
    profile = load_profile()
    cmd = [claude_bin(), "-p", "--output-format", "json", "--no-session-persistence", "--strict-mcp-config",
           "--model", profile.get("llm_model", "sonnet")]
    if web:
        cmd += ["--tools", "WebSearch,WebFetch", "--allowedTools", "WebSearch", "WebFetch",
                "--permission-mode", "dontAsk"]
    else:
        cmd += ["--tools", ""]
    # Run from your data/ folder so no project CLAUDE.md or settings leak into the prompt.
    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=data_dir())
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise ClaudeError((proc.stderr or proc.stdout)[:500]) from e
    if out.get("is_error"):
        raise ClaudeError(str(out.get("result"))[:500])
    return out.get("result", "")


def output_language(p: dict | None = None) -> str:
    """The language everything Claude writes for you is in: your profile's app language (Profile page)."""
    p = p or load_profile()
    if p.get("language") == "pt":
        return ("Write every text value in European Portuguese (pt-PT, AO90; never Brazilian Portuguese). "
                "Keep the JSON keys, and any fixed values listed with |, exactly as given, in English.")
    return "Write every text value in English. Keep the JSON keys exactly as given."


def parse_json(text: str) -> dict:
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ClaudeError(f"Claude didn't return valid JSON: {text[:300]}") from e


def _me(stack: str | None = None) -> str:
    """You, for a prompt. `stack` is the posting's (scoring.stack): Node/TS postings get your Node CV if you have one."""
    p = load_profile()
    lang = ("Write in European Portuguese (pt-PT, AO90; never Brazilian Portuguese)." if p.get("language") == "pt"
            else "Write in English.")
    rules = "\n".join(f"- {r}" for r in [*p.get("outreach_rules", []), lang])
    return f"""<candidate>
Name: {p['name']} · {p.get('linkedin_url', '')} · {p.get('github_url', '')}

CV:
{cv_text(stack)}

Story (in their words):
{p.get('story', '')}

Field: {p['field_def']['label']}
Experience, as they count it: {p.get('experience_years', 1)} year(s) of professional experience in the roles they want
({', '.join(p['field_def']['roles'][r]['label'] for r in p.get('roles', []))}).
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
  "gaps": ["real gaps or blockers: {gaps}"],
  "angle": "the one thing to lead with when applying",
  "company_type": {types}
}}

Judge "years" against the experience they count above, not the CV's dates: a role asking for clearly more
is a real gap. {note}

{language}"""


def assess_job(conn: sqlite3.Connection, job_id: int) -> dict:
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    p = load_profile()
    w = p["field_def"]["words"]
    result = parse_json(run_claude(ASSESS.format(me=_me(job["stack"]), job=_job_block(job), gaps=w["gaps"],
                                                 types=w["research_types"], note=w["assess_note"],
                                                 language=output_language(p))))
    conn.execute("UPDATE jobs SET assessment = ? WHERE dedup_key = ?", (json.dumps(result), job["dedup_key"]))
    conn.commit()
    return result


# ---------- research ----------

RESEARCH = """Research this company for a job seeker who wants to reach out directly to its {team}.
Use web search and fetch pages. Only report what you actually found; put the source URL next to every
person and every non-obvious claim. Do NOT guess email addresses. If you can't find something, leave it empty.

Company: {name}
{hint}
Open {roles_noun} we know of: {roles}

Find:
1. What the company does, industry, size, where the {team} sits (presence in {where}? remote policy?).
2. {focus}
3. Up to 6 people worth contacting, by public role: {people}.
   Name, role, why them, and the public URL where you found them (LinkedIn, company site, talk, article).
4. One or two specific, recent things (product launch, migration, blog post, expansion) the candidate could
   mention to show genuine interest.

Return ONLY a JSON object:
{{
  "summary": "2-3 sentences",
  "industry": "...",
  "company_type": {types},
  "is_startup": true | false,
  "stage": "e.g. Seed, Series A (2025, €12M), bootstrapped, public, or empty",
  "headcount": "approximate, with source, or empty",
  "local_presence": "what you found about them in {where}, or empty",
  "remote_policy": "...",
  "team_evidence": [{{"what": "...", "url": "..."}}],
  "focus": ["{focus_label}: short items"],
  "careers_url": "...",
  "people": [{{"name": "...", "role": "...", "why": "...", "url": "..."}}],
  "hooks": [{{"what": "...", "url": "..."}}],
  "fit_note": "1-2 sentences: why this candidate specifically could be valuable to them"
}}

{language}

The candidate, for the fit note:
{cv}"""


def research_company(conn: sqlite3.Connection, company_id: int) -> dict:
    c = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
    roles = [r[0] for r in conn.execute(
        "SELECT DISTINCT title FROM jobs WHERE company_key = ? ORDER BY score DESC LIMIT 8", (c["key"],))]
    hint = f"Note: {c['note']}" if c["note"] else ""
    p = load_profile()
    w = p["field_def"]["words"]
    where = p["country"] or p["home_city"]
    roles_wanted = ", ".join(p["field_def"]["roles"][r]["label"] for r in p["roles"])
    prompt = RESEARCH.format(name=c["name"], hint=hint, roles=", ".join(roles) or "none known",
                             cv=cv_text()[:4000], where=where, team=w["team"], roles_noun=w["roles"],
                             focus=w["research_focus"], focus_label=w["focus_label"], types=w["research_types"],
                             people=w["research_people"].format(roles_wanted=roles_wanted, where=where),
                             language=output_language(p))
    result = parse_json(run_claude(prompt, web=True))
    kind = w["research_type_map"].get(result.get("company_type", ""))
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

{language}

Return ONLY a JSON object:
{{
{fields}
}}"""

# What each message button writes. The cover note comes with its email subject.
JOB_MESSAGES = {
    "cover": {"cover_note": "120-180 words for the application form / email. Lead with the angle. No 'Dear Sir/Madam'.",
              "subject": "email subject line"},
    "recruiter": {"linkedin_note_recruiter": "LinkedIn connection note to the recruiter for this role, max 280 characters."},
    "manager": {"message_hiring_manager": "70-120 words to {manager}: why this team, one proof point, a soft ask."},
}

DRAFT_COMPANY = """Write cold outreach from this candidate to {intro}.
There may be no open role that fits; the goal is a short conversation and being remembered when one opens.
They will edit and send these manually.

{me}

<company>
Name: {name}
Startup: {startup}
Research: {research}
Open {roles_noun}: {roles}
</company>

<person>{person}</person>

{note}

{language}

Return ONLY a JSON object:
{{
  "linkedin_note": "connection request note, max 280 characters, specific to this person/company",
  "message": "80-140 words after they accept, or as an email: who I am, where I'm coming from, why THIS company's {team} (use a hook from the research), the ask (15 minutes, or who to talk to).",
  "followup": "40-70 words for a polite follow-up a week later, adding one new detail",
  "subject": "email subject line"
}}"""


def draft_for_job(conn: sqlite3.Connection, job_id: int, kinds: list[str] | None = None) -> dict:
    """Write the messages in `kinds` (keys of JOB_MESSAGES; all by default), keeping the others already drafted."""
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assessment = f"<assessment>{job['assessment']}</assessment>" if job["assessment"] else ""
    p = load_profile()
    manager = p["field_def"]["words"]["manager"]
    wanted = {k: v.format(manager=manager) for kind in (kinds or JOB_MESSAGES) for k, v in JOB_MESSAGES[kind].items()}
    fields = ",\n".join(f"  {json.dumps(k)}: {json.dumps(v)}" for k, v in wanted.items())
    result = parse_json(run_claude(DRAFT_JOB.format(me=_me(job["stack"]), job=_job_block(job), assessment=assessment,
                                                    fields=fields, language=output_language(p))))
    # Re-read: another message for this job may have been drafted while Claude was writing this one.
    current = conn.execute("SELECT drafts FROM jobs WHERE id = ?", (job_id,)).fetchone()["drafts"]
    drafts = {**json.loads(current or "{}"), **{k: result[k] for k in wanted if k in result}}
    conn.execute("UPDATE jobs SET drafts = ? WHERE dedup_key = ?", (json.dumps(drafts), job["dedup_key"]))
    conn.commit()
    return drafts


def draft_for_company(conn: sqlite3.Connection, company_id: int, person: str = "") -> dict:
    c = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
    roles = [r[0] for r in conn.execute(
        "SELECT DISTINCT title FROM jobs WHERE company_key = ? AND rejected IS NULL ORDER BY score DESC LIMIT 5",
        (c["key"],))]
    p = load_profile()
    w = p["field_def"]["words"]
    person = person or f"Not specified: write for {w['default_person']}."
    result = parse_json(run_claude(DRAFT_COMPANY.format(
        intro=w["company_intro"], roles_noun=w["roles"], team=w["team"], note=w["outreach_note"],
        language=output_language(p),
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
