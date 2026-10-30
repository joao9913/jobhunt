"""Rule-based ranking against profile.yaml. Fast and deterministic; Claude only looks at the top."""

from __future__ import annotations

import json
import re
import sqlite3

from .core import PORTUGAL_PLACES, ascii_lower, has_term, load_profile

ENG_TITLE = re.compile(
    r"engineer|developer|programmer|software|backend|back-end|python|django|devops|\bsre\b|"
    r"platform|full.?stack|data|integration|\bapi\b|technical lead|tech lead|desenvolvedor|programador|"
    r"engenheiro|entwickler",
    re.I,
)


REMOTE_EU = re.compile(
    r"remote[^.\n]{0,60}\b(europe|european|eu|emea|portugal|cet|cest|gmt|worldwide|anywhere)\b|"
    r"\b(europe|eu|emea)[^.\n]{0,30}remote", re.I)
REMOTE_NON_EU = re.compile(
    r"(must|need to|required to) (be )?(located|based|reside|live) in the (us|u\.s\.|united states|usa|americas)|"
    r"\b(us|u\.s\.)[- ](based|only|residents?)\b|remote[^.\n]{0,40}\b(us|usa|united states|latam|americas|india|apac)\b only", re.I)


RESIDENCY = re.compile(
    r"(must|need to|required to|should) (be )?(located|based|reside|live|resident) in (?!the eu|europe|the european)|"
    r"right to work in (the uk|germany|france|the netherlands|spain|poland|ireland)|"
    r"(only|exclusively) (candidates|applicants) (based|located|residing) in", re.I)

_STOP = {
    "en": "the and to of you we with for our will are your this that",
    "pt": "de para com uma não você os das dos são equipa",
    "es": "el los las del para con una que por somos nuestro",
    "fr": "le les des et pour avec nous vous une est sur dans",
    "de": "und der die das wir mit für sie ist ein eine auf",
    "nl": "het een van wij voor met jij zijn op ook",
    "it": "il della per con una sono che gli nel siamo",
    "pl": "się jest dla oraz nasz który są będzie pracy jako",
}
_STOP_SETS = {k: set(v.split()) for k, v in _STOP.items()}


def posting_language(text: str) -> str:
    words = re.findall(r"[a-zà-ÿ]+", text.lower())[:600]
    if len(words) < 25:
        return "en"  # too little text to tell; don't punish
    counts = {lang: sum(w in stop for w in words) for lang, stop in _STOP_SETS.items()}
    return max(counts, key=counts.get)


def is_engineering_title(title: str) -> bool:
    return bool(ENG_TITLE.search(title))


class Scorer:
    def __init__(self, profile: dict | None = None) -> None:
        p = profile or load_profile()
        self.p = p
        t = p["titles"]
        self.include = [s.lower() for s in t["include"]]
        self.exclude = [s.lower() for s in t["exclude"]]
        self.exclude_re = [re.compile(r, re.I) for r in t.get("exclude_regex", [])]
        self.title_bonus = {k.lower(): v for k, v in (t.get("bonus") or {}).items()}
        self.title_penalty = {k.lower(): v for k, v in (t.get("penalty") or {}).items()}
        self.skills = {k.lower(): v for k, v in p["skills"].items()}
        self.red_flags = [(re.compile(f["pattern"], re.I), f["points"], f["reason"]) for f in p.get("red_flags", [])]
        loc = p["location"]
        self.home = loc["home"]
        self.country = loc["country"]
        self.other_onsite = loc.get("other_ok_onsite") or []
        self.remote_ok = loc["remote_ok"]
        self.remote_reject = loc["remote_reject"]
        self.excluded_companies = {s.lower() for s in p.get("exclude_companies", [])}

    # Returns (score, reasons, rejected_reason). A rejected job gets score 0.
    def score(self, job: sqlite3.Row | dict) -> tuple[int, list[str], str | None]:
        title = (job["title"] or "").lower()
        desc = (job["description"] or "").lower()
        location = (job["location"] or "").lower()
        reasons: list[str] = []

        if (job["company"] or "").lower().strip() in self.excluded_companies:
            return 0, [], "excluded company"
        for word in self.exclude:
            if has_term(title, word):
                return 0, [], f"title: {word}"
        for rx in self.exclude_re:
            if rx.search(title):
                return 0, [], f"title: {rx.pattern}"
        if not any(has_term(title, w) for w in self.include):
            return 0, [], "title not a backend/dev role"

        loc_ok, loc_pts, loc_reason, _ = self._location(job, title, location, desc)
        if not loc_ok:
            return 0, [], loc_reason
        score = 20 + loc_pts
        if loc_reason:
            reasons.append(loc_reason)

        for word, pts in self.title_bonus.items():
            if has_term(title, word):
                score += pts
                reasons.append(f"title +{word}")
        for word, pts in self.title_penalty.items():
            if word.strip(" .") and (word in title if not word.isalpha() else has_term(title, word)):
                score -= pts
                reasons.append(f"title -{word.strip()}")

        hits = [s for s in self.skills if has_term(desc, s) or has_term(title, s)]
        skill_pts = sum(self.skills[s] for s in hits)
        score += min(skill_pts, 55)
        if hits:
            reasons.append("skills: " + ", ".join(s for s in hits if self.skills[s] > 0))
        if desc and "python" not in desc and "python" not in title:
            score -= 15
            reasons.append("no Python mentioned")
        if not desc:
            reasons.append("no description yet")

        flagged: set[str] = set()
        for rx, pts, why in self.red_flags:
            if why not in flagged and rx.search(desc):
                flagged.add(why)
                score -= pts
                reasons.append(f"-{why}")

        return max(0, min(100, score)), reasons, None

    def remote_check(self, job: sqlite3.Row | dict) -> bool:
        """True when the posting doesn't say whether it hires someone living in Lisbon: ask before applying."""
        title, desc, location = ((job[k] or "").lower() for k in ("title", "description", "location"))
        return self._location(job, title, location, desc)[3]

    # Returns (ok, points, reason, check). You live in Lisbon and won't move, so a posting is only ok if you
    # can do it from there: Lisbon area (any mode), remote from Portugal, or remote open to Europe.
    # `check` marks postings that don't say whether they hire from Portugal.
    def _location(self, job, title: str, location: str, desc: str) -> tuple[bool, int, str, bool]:
        remote = job["remote"]
        if re.search(r"\bhybrid\b|\bh[ií]brido\b|on-?site|presencial", title):
            remote = False  # the title beats the search filter
        text = f"{location} {title}"
        if remote is None:
            remote = bool(re.search(r"\bremote\b|remoto|teletrabalho|home.?office|anywhere", text)) or bool(
                re.search(r"fully remote|100% remote|remote.first|work from anywhere", desc)
            )
        in_home = any(has_term(location, w) for w in self.home)
        in_country = in_home or any(has_term(location, w) for w in self.country)
        if in_home:
            return True, 10, "Lisbon area", False
        if in_country:
            if remote:
                return True, 6, "Portugal remote", False
            place = ascii_lower(location)
            elsewhere = [p for p in PORTUGAL_PLACES if p not in self.home and has_term(place, p)]
            if elsewhere:
                return False, 0, f"on-site/hybrid outside Lisbon: {location[:40]}", False
            return True, 2, "Portugal (city not given)", True
        if any(has_term(location, w) for w in self.other_onsite):
            return True, 0, "acceptable city", False
        if remote:
            lives_there = _residency_outside_portugal(desc)
            if any(has_term(text, w) for w in self.remote_ok) or REMOTE_EU.search(desc):
                if lives_there:
                    return False, 0, "remote, but asks you to live in another country", False
                return True, 6, "remote EU-friendly", False
            if any(has_term(location, w) for w in self.remote_reject):
                return False, 0, f"remote, restricted: {location[:40]}", False
            if REMOTE_NON_EU.search(desc):
                return False, 0, "remote, but only US/Americas/Asia", False
            if location.strip() and location.strip() != "remote":
                # "Remote" shown with a city/country elsewhere: sometimes EU-wide, sometimes "must live here".
                where = location[:40]
                lang = posting_language(f"{title} {desc}")
                if lang not in ("en", "pt"):
                    return False, 0, f"remote in {where}, posting in {lang}: local hires only", False
                if lives_there:
                    return False, 0, f"remote in {where}, asks you to live there", False
                return True, -8 if not desc else -4, f"remote, listed in {where} (check they hire from Portugal)", True
            return True, 0, "remote (region unclear)", True
        if not location.strip():
            return True, -5, "location unknown", True
        return False, 0, f"on-site: {location[:40]}", False


def _residency_outside_portugal(desc: str) -> bool:
    m = RESIDENCY.search(desc)
    return bool(m) and "portugal" not in desc[m.start():m.end() + 80]


def rescore_all(conn: sqlite3.Connection, scorer: Scorer | None = None) -> int:
    scorer = scorer or Scorer()
    rows = conn.execute("SELECT id, company, title, description, location, remote FROM jobs").fetchall()
    for r in rows:
        s, reasons, rejected = scorer.score(r)
        conn.execute(
            "UPDATE jobs SET score = ?, reasons = ?, rejected = ?, remote_check = ? WHERE id = ?",
            (s, json.dumps(reasons), rejected, int(rejected is None and scorer.remote_check(r)), r["id"]),
        )
    conn.commit()
    return len(rows)


def refresh_company_stats(conn: sqlite3.Connection, min_score: int) -> None:
    conn.execute(
        """UPDATE companies SET
             eng_jobs = (SELECT COUNT(DISTINCT dedup_key) FROM jobs
                         WHERE jobs.company_key = companies.key AND last_seen >= date('now', '-45 day')),
             fit_jobs = (SELECT COUNT(DISTINCT dedup_key) FROM jobs
                         WHERE jobs.company_key = companies.key AND rejected IS NULL AND score >= ?
                           AND last_seen >= date('now', '-45 day')),
             best_score = COALESCE((SELECT MAX(score) FROM jobs WHERE jobs.company_key = companies.key
                                      AND rejected IS NULL), 0)""",
        (min_score,),
    )
    conn.commit()
