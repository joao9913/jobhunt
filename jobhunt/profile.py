"""Your search profile: what you edit on the Profile page, and the full settings the rest of the app reads.

`profile.yaml` (not in git) holds only what's personal: your field (see fields.py), who you are, the job types
you want, your skills, where you live. `load()` expands it into the settings scoring and the sources use: which
titles count, which are dropped, what to search for on each site. A CV can fill most of it through Claude
(`from_cv`). With accounts, each user has their own profile.yaml (core.profile_path()).
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import yaml

from . import fields
from .core import _CODES, _COUNTRIES, data_dir, fold, html_to_text, profile_path


def cv_text_path() -> Path:
    return data_dir() / "cv.txt"  # the uploaded CV as plain text; what Claude reads


def draft_path() -> Path:
    return data_dir() / "profile_draft.json"  # Claude's suggestions from a CV, until you save or discard them

# Job types, title words, sources and wording live in fields.py; ROLES is the tech field's, for old imports.
ROLES = fields.TECH_ROLES
FIELD_CHOICES = {k: f["label"] for k, f in fields.FIELDS.items()}
LANGUAGE_CHOICES = {"en": "English", "pt": "Português (PT)"}

# Tech whose names need care as whole words: "java" must not drop "JavaScript", "go" is a common word.
TECH_REGEX = {"java": r"\bjava\b(?!script)", "go": r"\bgo\b|\bgolang\b", "c": r"\bc\b(?![+#])", "r": r"\br\b"}

LANGUAGES = {"english": "en", "portuguese": "pt", "spanish": "es", "french": "fr", "german": "de", "dutch": "nl",
             "italian": "it", "polish": "pl", "swedish": "sv", "danish": "da", "norwegian": "no", "finnish": "fi",
             "czech": "cs"}

# The defaults for anything profile.yaml doesn't set. Everything here can be overridden in profile.yaml.
DEFAULTS: dict = {
    "field": "tech",
    "language": None,  # the app's language and Claude's: "en" or "pt" (pt-PT); unset = the field's default
    "name": "", "email": "", "linkedin_url": "", "github_url": "", "story": "",
    "experience_years": 2, "experience_note": "",
    "roles": [],  # the field's default_roles
    "skills": {},
    "must_have": [],
    "avoid": [],
    "languages": ["english"],
    "search_terms": [],
    "location": {"city": "", "nearby": [], "country": "", "remote": None, "onsite_elsewhere": []},  # remote: field default
    "exclude_companies": [],
    "min_score": 40,
    "outreach_rules": [
        "Never claim experience that isn't in the CV or the story.",
        "Be specific about the company; one concrete reason, not flattery.",
        "Short. Ask for a 15-minute chat or for the right person to talk to, not for \"a job\".",
    ],  # plus a rule to write in your app language (llm._me)
    "red_flags": None,  # the field's (fields.py); set your own list in profile.yaml to replace them
    "remote_ok": ["europe", "european", "eu", "emea", "cet", "cest", "wet", "gmt", "utc", "worldwide", "anywhere",
                  "global", "international"],
    "remote_reject": ["us", "usa", "us only", "usa only", "united states", "us-based", "u.s.", "north america",
                      "canada", "latam", "latin america", "americas", "apac", "asia", "india", "australia", "brazil",
                      "est", "pst", "us timezones"],
    "linkedin": {"enabled": True, "max_detail_fetches": None, "max_closed_checks": 60},
    "wellfound": {"enabled": True, "max_pages": 4},
    "yc_jobs": {"enabled": True, "pages": ["jobs/role/software-engineer/remote", "jobs/role/software-engineer"]},
    "remotive_category": "software-dev",
    "hn_whos_hiring": True,
    "llm_model": "sonnet",
    "auto_assess": 40,
    "no_reply_after_days": 28,  # an application with no answer after this many days becomes "no reply"
    "seniority": "any",  # any | no-senior (drop senior postings) | junior-mid (only postings that say junior-mid)
}

SENIORITY_CHOICES = {"any": "Any level",
                     "no-senior": "Hide senior postings",
                     "junior-mid": "Only postings that say junior–mid (also hides the ones that don't say)"}

# The fields the Profile page edits; everything else in profile.yaml is kept as it is when saving.
EDITABLE = ["field", "language", "name", "email", "linkedin_url", "github_url", "story", "experience_years", "experience_note", "roles", "skills",
            "must_have", "avoid", "languages", "search_terms", "location", "exclude_companies", "min_score",
            "seniority"]


def read() -> dict:
    """profile.yaml as written, or {} before you've saved a profile."""
    path = profile_path()
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def exists() -> bool:
    raw = read()
    return bool(raw.get("name") or raw.get("skills"))


def editable() -> dict:
    """The Profile page's values: profile.yaml over the defaults."""
    raw = read()
    out = {k: raw.get(k, DEFAULTS[k]) for k in EDITABLE}
    f = fields.get(out["field"])
    out["roles"] = [r for r in out["roles"] or [] if r in f["roles"]] or list(f["default_roles"])
    out["language"] = out["language"] if out["language"] in LANGUAGE_CHOICES else f["default_language"]
    out["location"] = {**DEFAULTS["location"], **(raw.get("location") or {})}
    if out["location"]["remote"] is None:
        out["location"]["remote"] = f["remote_default"]
    return out


class _Dumper(yaml.SafeDumper):
    """Writes multi-line text (story, notes) as readable | blocks."""


_Dumper.add_representer(str, lambda d, s: d.represent_scalar("tag:yaml.org,2002:str", s, style="|" if "\n" in s else None))


def save(values: dict) -> None:
    raw = read()
    raw.update({k: values[k] for k in EDITABLE if k in values})
    profile_path().write_text("# Your search profile. Edit it on the dashboard's Profile page (or here, then run "
                            "`jobhunt score`).\n" + yaml.dump(raw, Dumper=_Dumper, sort_keys=False,
                                                              allow_unicode=True, width=110))


def load() -> dict:
    """Everything the app reads: profile.yaml over the defaults, expanded into titles, searches and filters."""
    raw = read()
    p = {**DEFAULTS, **raw}
    f = fields.get(p.get("field"))
    p["field"] = p.get("field") if p.get("field") in fields.FIELDS else "tech"
    p["field_def"] = f
    p["language"] = p.get("language") if p.get("language") in LANGUAGE_CHOICES else f["default_language"]
    loc = {**DEFAULTS["location"], **(p.get("location") or {})}
    if loc["remote"] is None:
        loc["remote"] = f["remote_default"]
    p["location"] = loc
    years = p.get("experience_years") or 0
    roles_def = f["roles"]
    roles = [r for r in p.get("roles") or [] if r in roles_def] or list(f["default_roles"])
    must = [fold(s) for s in p.get("must_have") or []]

    chosen = {w for r in roles for w in roles_def[r]["words"]}
    others = {w for r in roles_def if r not in roles for w in roles_def[r]["words"]} - chosen
    exclude = list(f["not_titles"])
    if not f["titles_required"]:
        exclude += sorted(others)  # tech: a title naming a type you didn't tick is never yours
    if years >= 1:
        exclude += f["junior_titles"]
    if years < 6:
        exclude += f["top_titles"]
    avoid = [fold(a).strip() for a in p.get("avoid") or [] if a.strip()]
    exclude += [a for a in avoid if a not in TECH_REGEX]
    spoken = {s.lower() for s in p.get("languages") or []}
    foreign = [lang for lang in LANGUAGES if lang not in spoken and lang != "english"]
    codes = [LANGUAGES[lang] for lang in foreign if LANGUAGES[lang] not in ("no",)]
    exclude_regex = [TECH_REGEX[a] for a in avoid if a in TECH_REGEX]
    if foreign:
        exclude_regex.append(rf"\b({'|'.join(foreign)})\b")
    if codes:
        exclude_regex += [rf"[/(]\s*({'|'.join(codes)})\b", rf"\b({'|'.join(codes)})\s*[/)]"]

    bonus = {w: 12 for w in must}
    for r in roles:
        bonus.update(roles_def[r]["bonus"])
    if years <= 3:
        bonus.update({"junior": 6, "mid": 4, "medior": 4})
    penalty = ({"senior": 20, "sr.": 20, "sr ": 20, "lead": 25, "expert": 20} if years < 3 else
               {"senior": 6, "sr.": 6, "sr ": 6, "lead": 12, "expert": 8} if years < 5 else {})
    if f["titles_required"]:
        # Psychology: the title must say psychologist; the job types only rank. A title that names only types you
        # didn't tick ("Psicólogo/a Forense" when you didn't tick forensic) is dropped.
        titles = {"include": [], "required": f["titles"], "unticked": sorted(others), "ticked": sorted(chosen)}
    else:
        titles = {"include": [*f["titles"], *sorted(chosen), *must], "required": [], "unticked": [], "ticked": []}
    p.setdefault("titles", {**titles, "exclude": exclude, "exclude_regex": exclude_regex, "bonus": bonus,
                            "penalty": penalty, "reject_label": f["reject_label"]})
    p["roles"] = roles

    if not p.get("skills"):  # no CV yet: at least rank by the job types
        p["skills"] = {w: 4 for r in roles for w in roles_def[r]["bonus"]}

    if p.get("red_flags") is None:
        p["red_flags"] = f["red_flags"]
    if foreign:
        names = "|".join(foreign)
        p["red_flags"] = [*p["red_flags"],
                          {"pattern": rf"\b(?:{names})\b[^.\n]{{0,40}}\b(?:fluent|native|required|mandatory|c1|c2|b2)\b",
                           "points": 25, "reason": "needs another language"},
                          {"pattern": rf"\b(?:fluent|native|required|mandatory|c1|c2|b2)\b[^.\n]{{0,40}}\b(?:{names})\b",
                           "points": 25, "reason": "needs another language"}]
    p["sources"] = p.get("sources") or f["sources"]
    p["seed_companies"] = f["seed_companies"]

    # Location, as scoring reads it.
    city, country = loc["city"].strip(), loc["country"].strip()
    code = next((c for c, name in _CODES.items() if name == country), "")
    home = [w.lower() for w in [city, *loc.get("nearby", [])] if w]
    p["home_city"] = city or country or "your city"
    p["country"] = country
    p["country_places"] = [c for c in _COUNTRIES.get(country, []) if c not in home]
    p["location_match"] = {"home": home, "country": [w for w in [country.lower(), code.lower()] if w],
                           "other_ok_onsite": [w.lower() for w in loc.get("onsite_elsewhere") or []],
                           "remote": bool(loc.get("remote", True)),
                           "remote_ok": [*p["remote_ok"], *([country.lower()] if country else []), *home],
                           "remote_reject": p["remote_reject"]}

    # What to search for on each site.
    terms = [t for t in p.get("search_terms") or [] if t.strip()] or [roles_def[r]["search"] for r in roles]
    li = {**DEFAULTS["linkedin"], **(p.get("linkedin") or {})}
    if "searches" not in li:
        where = country or city
        li["searches"] = [{"keywords": t, "location": where} for t in terms if where]
        if loc.get("remote", True):
            li["searches"] += [{"keywords": t, "location": "European Union", "remote": True} for t in terms[:2]]
    p["linkedin"] = li
    p.setdefault("himalayas_queries", terms[:3])
    wf = {**DEFAULTS["wellfound"], **(p.get("wellfound") or {})}
    if "pages" not in wf:
        slugs = [roles_def[r]["wellfound"] for r in roles if "wellfound" in roles_def[r]][:3]
        place = re.sub(r"[^a-z]+", "-", city.lower()).strip("-")
        wf["pages"] = [*(f"role/l/{s}/{place}" for s in slugs if place), *(f"role/r/{s}" for s in slugs
                                                                            if loc.get("remote", True))]
    p["wellfound"] = wf
    p["search_terms_used"] = terms
    p["focus_words"] = must or [w for r in roles for w in roles_def[r]["words"]]  # what a HN post must mention
    return p


# ---------- CV ----------


def cv_to_text(path: Path) -> str:
    """Plain text from a PDF, Word, HTML, Markdown or text CV."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages).strip()
    if suffix == ".docx":
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
        xml = re.sub(r"</w:p>", "\n", xml)
        return html_to_text(re.sub(r"<[^>]+>", "", xml))
    raw = path.read_text(errors="ignore")
    return html_to_text(raw) if suffix in {".html", ".htm"} else raw.strip()


FROM_CV = """Read this CV and fill in a job-search profile for its owner, who is looking for work in {field}. Be accurate and conservative: only
use what the CV says. Return ONLY a JSON object:
{{
  "name": "full name",
  "email": "or empty",
  "linkedin_url": "full URL or empty",
  "github_url": "full URL or empty",
  "story": "4-6 sentences in the first person: background, what they've built, current role, what they want next. Only facts from the CV.",
  "experience_years": <integer: years of professional experience in the kind of role they'd apply for now. Count
                       jobs in that field; side projects, studies and unrelated jobs count little or not at all>,
  "experience_note": "1-2 sentences on how that number was counted, and any experience that's real but different (other field, freelance, academic)",
  "roles": [the job types that fit them, from: {roles}],
  "skills": {{"skill name in lowercase": <points 2-18>}},
  "must_have": ["{must}"],
  "avoid": ["{avoid}"],
  "languages": ["spoken languages, lowercase English names"],
  "search_terms": ["{searches}"],
  "location": {{"city": "city they live in, if stated, else empty", "country": "country in English, if stated, else empty"}}
}}

Include 10-25 skills. {skills}

{language} Skill names, search terms and the JSON keys stay as described above.

<cv>
{cv}
</cv>"""


def from_cv(cv: str) -> dict:
    """Claude's profile suggestions for a CV; saved as a draft for you to review."""
    from .llm import parse_json, run_claude

    p = load()
    f, w = p["field_def"], p["field_def"]["words"]
    from .llm import output_language

    found = parse_json(run_claude(FROM_CV.format(
        language=output_language(p), cv=cv[:20000], field=f["label"].lower(), roles=", ".join(f"{k} ({r['label']})" for k, r in f["roles"].items()),
        must=w["cv_must_have"], avoid=w["cv_avoid"], searches=w["cv_searches"], skills=w["cv_skills"])))
    draft = {k: v for k, v in found.items() if k in EDITABLE and k != "field" and v not in (None, "", [], {})}
    if "roles" in draft:
        draft["roles"] = [r for r in draft["roles"] if r in f["roles"]]
    if "skills" in draft:
        draft["skills"] = {fold(str(k)) if f["titles_required"] else str(k).lower(): int(v) for k, v in draft["skills"].items() if str(v).lstrip("-").isdigit()}
    if "location" in draft:
        draft["location"] = {k: v for k, v in draft["location"].items() if k in ("city", "country") and v}
        if draft["location"].get("country") not in _COUNTRIES:
            draft["location"].pop("country", None)
    draft_path().write_text(json.dumps(draft, indent=1))
    return draft


def draft() -> dict | None:
    path = draft_path()
    return json.loads(path.read_text()) if path.exists() else None


def discard_draft() -> None:
    draft_path().unlink(missing_ok=True)
