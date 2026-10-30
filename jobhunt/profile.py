"""Your search profile: what you edit on the Profile page, and the full settings the rest of the app reads.

`profile.yaml` (not in git) holds only what's personal: who you are, the job types you want, your skills,
where you live. `load()` expands it into the settings scoring and the sources use: which titles count,
which are dropped, what to search for on each site. A CV can fill most of it through Claude (`from_cv`).
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import yaml

from .core import _CODES, _COUNTRIES, DATA, PROFILE_PATH, html_to_text

CV_TEXT = DATA / "cv.txt"  # the uploaded CV as plain text; what Claude reads
DRAFT_PATH = DATA / "profile_draft.json"  # Claude's suggestions from a CV, until you save or discard them

# ---------- job types ----------
# words: title words that make a posting this type. Chosen types are searched for; the others' words drop a
# posting by title (so a backend profile never sees "Frontend Engineer"), unless a chosen type uses them too.
ROLES: dict[str, dict] = {
    "backend": {"label": "Backend", "words": ["backend", "back-end", "back end", "api engineer", "integration engineer",
                                               "platform engineer"],
                "bonus": {"backend": 10, "back-end": 10, "back end": 10, "platform": 3, "integration": 3, "api": 3},
                "search": "backend engineer", "wellfound": "backend-engineer"},
    "frontend": {"label": "Frontend", "words": ["frontend", "front-end", "front end", "ui engineer", "ui developer"],
                 "bonus": {"frontend": 10, "front-end": 10, "front end": 10, "ui": 3},
                 "search": "frontend developer", "wellfound": "frontend-engineer"},
    "fullstack": {"label": "Full stack", "words": ["full stack", "full-stack", "fullstack"],
                  "bonus": {"full stack": 8, "full-stack": 8, "fullstack": 8},
                  "search": "full stack developer", "wellfound": "full-stack-engineer"},
    "mobile": {"label": "Mobile", "words": ["ios", "android", "mobile", "flutter", "react native"],
               "bonus": {"mobile": 8, "ios": 8, "android": 8, "flutter": 6, "react native": 6},
               "search": "mobile developer", "wellfound": "mobile-engineer"},
    "data": {"label": "Data engineering", "words": ["data engineer", "analytics engineer", "etl", "data platform"],
             "bonus": {"data engineer": 10, "analytics engineer": 8, "data platform": 6},
             "search": "data engineer", "wellfound": "data-engineer"},
    "devops": {"label": "DevOps / SRE / cloud", "words": ["devops", "sre", "site reliability", "infrastructure",
                                                         "cloud engineer", "platform engineer"],
               "bonus": {"devops": 10, "sre": 10, "site reliability": 10, "infrastructure": 6, "cloud": 4},
               "search": "devops engineer", "wellfound": "devops-engineer"},
    "ml": {"label": "Machine learning / AI", "words": ["machine learning", "ml engineer", "ai engineer", "mlops",
                                                       "data scientist", "research"],
           "bonus": {"machine learning": 10, "ml": 8, "ai": 6, "mlops": 6},
           "search": "machine learning engineer", "wellfound": "machine-learning-engineer"},
    "qa": {"label": "QA / test automation", "words": ["qa", "quality assurance", "test automation", "sdet", "tester",
                                                       "in test"],
           "bonus": {"qa": 8, "test automation": 8, "sdet": 8},
           "search": "qa automation engineer", "wellfound": "qa-engineer"},
    "embedded": {"label": "Embedded / firmware", "words": ["embedded", "firmware", "hardware"],
                 "bonus": {"embedded": 10, "firmware": 10},
                 "search": "embedded software engineer", "wellfound": "embedded-engineer"},
    "security": {"label": "Security", "words": ["security engineer", "appsec", "application security"],
                 "bonus": {"security": 8},
                 "search": "security engineer", "wellfound": "security-engineer"},
}

GENERIC_TITLES = ["software engineer", "software developer", "software development engineer", "developer",
                  "engineer", "programmer"]
# Never developer jobs for anyone using this.
NOT_DEV = ["manager", "director", "head of", "vp", "vice president", "sales", "presales", "pre-sales", "account",
           "marketing", "designer", "recruiter", "support", "consultant", "analyst", "sap", "salesforce",
           "servicenow", "dynamics", "network engineer", "electrical", "mechanical", "civil", "mainframe", "cobol",
           "game", "unity", "unreal", "blockchain", "web3", "solidity", "working student", "werkstudent"]
# Tech whose names need care as whole words: "java" must not drop "JavaScript", "go" is a common word.
TECH_REGEX = {"java": r"\bjava\b(?!script)", "go": r"\bgo\b|\bgolang\b", "c": r"\bc\b(?![+#])", "r": r"\br\b"}

LANGUAGES = {"english": "en", "portuguese": "pt", "spanish": "es", "french": "fr", "german": "de", "dutch": "nl",
             "italian": "it", "polish": "pl", "swedish": "sv", "danish": "da", "norwegian": "no", "finnish": "fi",
             "czech": "cs"}

# The defaults for anything profile.yaml doesn't set. Everything here can be overridden in profile.yaml.
DEFAULTS: dict = {
    "name": "", "email": "", "linkedin_url": "", "github_url": "", "story": "",
    "experience_years": 2, "experience_note": "",
    "roles": ["backend"],
    "skills": {},
    "must_have": [],
    "avoid": [],
    "languages": ["english"],
    "search_terms": [],
    "location": {"city": "", "nearby": [], "country": "", "remote": True, "onsite_elsewhere": []},
    "exclude_companies": [],
    "min_score": 40,
    "outreach_rules": [
        "Never claim experience that isn't in the CV or the story.",
        "Be specific about the company; one concrete reason, not flattery.",
        "Short. Ask for a 15-minute chat or for the right person to talk to, not for \"a job\".",
        "Write in English unless the posting or company is clearly local-language, then use that language.",
    ],
    "red_flags": [
        {"pattern": r"\b(for|with) (one of )?our clients?\b|\b(on behalf of|for) an? (leading |global |major |"
                    r"international )?client\b|nearshore|near-shore|outsourcing|staff augmentation|body.?shop|"
                    r"allocated to (a|our) client|client projects?\b",
         "points": 15, "reason": "consultancy / outsourcing"},
        {"pattern": r"\bsecurity clearance\b", "points": 40, "reason": "security clearance"},
        {"pattern": r"\b(?:us|u\.s\.) (?:citizens?|persons?)\b", "points": 40, "reason": "US citizens only"},
    ],
    "remote_ok": ["europe", "european", "eu", "emea", "cet", "cest", "wet", "gmt", "utc", "worldwide", "anywhere",
                  "global", "international"],
    "remote_reject": ["us", "usa", "us only", "usa only", "united states", "us-based", "u.s.", "north america",
                      "canada", "latam", "latin america", "americas", "apac", "asia", "india", "australia", "brazil",
                      "est", "pst", "us timezones"],
    "linkedin": {"enabled": True, "max_detail_fetches": 150, "max_closed_checks": 60},
    "wellfound": {"enabled": True, "max_pages": 4},
    "yc_jobs": {"enabled": True, "pages": ["jobs/role/software-engineer/remote", "jobs/role/software-engineer"]},
    "remotive_category": "software-dev",
    "hn_whos_hiring": True,
    "llm_model": "sonnet",
    "auto_assess": 40,
}

# The fields the Profile page edits; everything else in profile.yaml is kept as it is when saving.
EDITABLE = ["name", "email", "linkedin_url", "github_url", "story", "experience_years", "experience_note", "roles", "skills",
            "must_have", "avoid", "languages", "search_terms", "location", "exclude_companies", "min_score"]


def read() -> dict:
    """profile.yaml as written, or {} before you've saved a profile."""
    if not PROFILE_PATH.exists():
        return {}
    return yaml.safe_load(PROFILE_PATH.read_text()) or {}


def exists() -> bool:
    raw = read()
    return bool(raw.get("name") or raw.get("skills"))


def editable() -> dict:
    """The Profile page's values: profile.yaml over the defaults."""
    raw = read()
    out = {k: raw.get(k, DEFAULTS[k]) for k in EDITABLE}
    out["location"] = {**DEFAULTS["location"], **(raw.get("location") or {})}
    return out


class _Dumper(yaml.SafeDumper):
    """Writes multi-line text (story, notes) as readable | blocks."""


_Dumper.add_representer(str, lambda d, s: d.represent_scalar("tag:yaml.org,2002:str", s, style="|" if "\n" in s else None))


def save(values: dict) -> None:
    raw = read()
    raw.update({k: values[k] for k in EDITABLE if k in values})
    PROFILE_PATH.write_text("# Your search profile. Edit it on the dashboard's Profile page (or here, then run "
                            "`jobhunt score`).\n" + yaml.dump(raw, Dumper=_Dumper, sort_keys=False,
                                                              allow_unicode=True, width=110))


def load() -> dict:
    """Everything the app reads: profile.yaml over the defaults, expanded into titles, searches and filters."""
    p = {**DEFAULTS, **read()}
    loc = {**DEFAULTS["location"], **(p.get("location") or {})}
    p["location"] = loc
    years = p.get("experience_years") or 0
    roles = [r for r in p.get("roles") or [] if r in ROLES] or ["backend"]
    must = [s.lower() for s in p.get("must_have") or []]

    chosen = {w for r in roles for w in ROLES[r]["words"]}
    others = {w for r in ROLES if r not in roles for w in ROLES[r]["words"]} - chosen
    exclude = [*NOT_DEV, *sorted(others)]
    if years >= 1:
        exclude += ["intern", "internship", "trainee"]
    if years < 6:
        exclude += ["principal", "principle", "staff", "architect"]
    avoid = [a.lower().strip() for a in p.get("avoid") or [] if a.strip()]
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
        bonus.update(ROLES[r]["bonus"])
    if years <= 3:
        bonus.update({"junior": 6, "mid": 4, "medior": 4})
    penalty = ({"senior": 20, "sr.": 20, "sr ": 20, "lead": 25, "expert": 20} if years < 3 else
               {"senior": 6, "sr.": 6, "sr ": 6, "lead": 12, "expert": 8} if years < 5 else {})
    p.setdefault("titles", {"include": [*GENERIC_TITLES, *sorted(chosen), *must], "exclude": exclude,
                            "exclude_regex": exclude_regex, "bonus": bonus, "penalty": penalty})
    p["roles"] = roles

    if not p.get("skills"):  # no CV yet: at least rank by the job types
        p["skills"] = {w: 4 for r in roles for w in ROLES[r]["bonus"]}

    if foreign:
        names = "|".join(foreign)
        p["red_flags"] = [*p["red_flags"],
                          {"pattern": rf"\b(?:{names})\b[^.\n]{{0,40}}\b(?:fluent|native|required|mandatory|c1|c2|b2)\b",
                           "points": 25, "reason": "needs another language"},
                          {"pattern": rf"\b(?:fluent|native|required|mandatory|c1|c2|b2)\b[^.\n]{{0,40}}\b(?:{names})\b",
                           "points": 25, "reason": "needs another language"}]

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
    terms = [t for t in p.get("search_terms") or [] if t.strip()] or [ROLES[r]["search"] for r in roles]
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
        slugs = [ROLES[r]["wellfound"] for r in roles][:3]
        place = re.sub(r"[^a-z]+", "-", city.lower()).strip("-")
        wf["pages"] = [*(f"role/l/{s}/{place}" for s in slugs if place), *(f"role/r/{s}" for s in slugs
                                                                            if loc.get("remote", True))]
    p["wellfound"] = wf
    p["focus_words"] = must or [w for r in roles for w in ROLES[r]["words"]]  # what a HN post must mention
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


FROM_CV = """Read this CV and fill in a job-search profile for its owner. Be accurate and conservative: only
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
  "skills": {{"skill name in lowercase": <points 2-18: 15-18 for their main language/framework, 6-10 for things they use often, 2-5 for familiar>}},
  "must_have": ["1-2 main languages or frameworks a posting should mention to be worth their time"],
  "avoid": ["languages/stacks common in their field that they do NOT work with, so titles naming them are dropped, e.g. java, .net, c#, php, ruby, go, rust, scala, kotlin, swift"],
  "languages": ["spoken languages, lowercase English names"],
  "search_terms": ["4-6 job-board searches for the roles they'd apply for, e.g. 'python backend', 'django developer'"],
  "location": {{"city": "city they live in, if stated, else empty", "country": "country in English, if stated, else empty"}}
}}

Include 10-25 skills. Use plain lowercase names job postings would use ("postgres", "react", "aws", "ci/cd").

<cv>
{cv}
</cv>"""


def from_cv(cv: str) -> dict:
    """Claude's profile suggestions for a CV; saved as a draft for you to review."""
    from .llm import parse_json, run_claude

    found = parse_json(run_claude(FROM_CV.format(cv=cv[:20000], roles=", ".join(ROLES))))
    draft = {k: v for k, v in found.items() if k in EDITABLE and v not in (None, "", [], {})}
    if "roles" in draft:
        draft["roles"] = [r for r in draft["roles"] if r in ROLES]
    if "skills" in draft:
        draft["skills"] = {str(k).lower(): int(v) for k, v in draft["skills"].items() if str(v).lstrip("-").isdigit()}
    if "location" in draft:
        draft["location"] = {k: v for k, v in draft["location"].items() if k in ("city", "country") and v}
        if draft["location"].get("country") not in _COUNTRIES:
            draft["location"].pop("country", None)
    DRAFT_PATH.write_text(json.dumps(draft, indent=1))
    return draft


def draft() -> dict | None:
    return json.loads(DRAFT_PATH.read_text()) if DRAFT_PATH.exists() else None


def discard_draft() -> None:
    DRAFT_PATH.unlink(missing_ok=True)
