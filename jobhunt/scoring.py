"""Rule-based ranking against profile.yaml. Fast and deterministic; Claude only looks at the top."""

from __future__ import annotations

import json
import re
import sqlite3

from .core import REMOTE_NO_COUNTRY, UNKNOWN_COUNTRY, ascii_lower, countries, has_term, load_profile

ENG_TITLE = re.compile(
    r"engineer|developer|programmer|software|backend|back-end|python|django|devops|\bsre\b|"
    r"platform|full.?stack|data|integration|\bapi\b|technical lead|tech lead|desenvolvedor|programador|"
    r"engenheiro|entwickler",
    re.I,
)


REMOTE_EU = re.compile(
    r"remote[^.\n]{0,60}\b(europe|european|eu|emea|cet|cest|gmt|worldwide|anywhere)\b|"
    r"\b(europe|eu|emea)[^.\n]{0,30}remote", re.I)
REMOTE_NON_EU = re.compile(
    r"(must|need to|required to) (be )?(located|based|reside|live) in the (us|u\.s\.|united states|usa|americas)|"
    r"\b(us|u\.s\.)[- ](based|only|residents?)\b|remote[^.\n]{0,40}\b(us|usa|united states|latam|americas|india|apac)\b only", re.I)


# Office attendance in the description: "3 days a week in the office", "Hybrid (2-3 days/week onsite)",
# "hybrid role based in Vilnius". Job boards often list these under remote, so the text decides.
_N = r"(?:\d|one|two|three|four|five)"
_DAYS = rf"(?:at least |minimum (?:of )?)?{_N}(?:\s*(?:-|–|to)\s*{_N})?\s*(?:days?|x|times)\s*(?:a|per|/|each|every|in the|of the)?\s*(?:week|wk)"
_OFFICE = r"(?:office|on-?site|in[- ]person|hq|headquarters)"
OFFICE_DAYS = re.compile(
    rf"{_DAYS}[^.\n]{{0,50}}{_OFFICE}|{_OFFICE}[^.\n]{{0,50}}{_DAYS}|hybrid (?:role|position|job) based in|"
    r"based in or near|regular (?:presence|attendance) (?:in|at) (?:the|our) office|office.(?:led|first) culture|"
    r"(?:location|work(?:ing)? (?:model|mode|policy|setup))\s*[:\-–]\s*hybrid|\|\s*hybrid\b|\bhybrid\s*\(", re.I)
HYBRID = re.compile(r"\bhybrid\b(?!\s*(?:cloud|infrastructure|infra|environments?|apps?|mobile|search|architecture|"
                    r"systems?|on-prem|deployments?))|\bh[ií]brido\b", re.I)
REMOTE_TOO = re.compile(r"fully remote|100% remote|remote.first|work from anywhere|full remote|remote-friendly|"
                        r"remote\s*(?:or|and|/)\s*hybrid|hybrid\s*(?:or|and|/)\s*remote", re.I)

RESIDENCY = re.compile(
    r"(must|need to|required to|should) (be )?(located|based|reside|live|resident) in (?!the eu|europe|the european)|"
    r"right to work in (the uk|germany|france|the netherlands|spain|poland|ireland)|"
    r"(only|exclusively) (candidates|applicants) (based|located|residing) in", re.I)

# ---------- seniority ----------
# Junior-mid: what it asks fits within 1-3 years ("2+", "1-3", "3 years"). Senior: asks for more, including
# open-ended "3+" / "at least 3" and ranges past 3 ("3-5"), or the title says so.

_NUM = r"\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|um|uma|dois|duas|tr[eê]s|quatro|cinco|seis|sete|oito|nove|dez"
_WORDS = {w: i for i, ws in enumerate(["", "one um uma", "two dois duas", "three tres três", "four quatro", "five cinco",
                                       "six seis", "seven sete", "eight oito", "nine nove", "ten dez"]) for w in ws.split()}
_YEARS = re.compile(
    rf"(?<![\d.,])(?P<a>{_NUM})\s*(?P<ap>\+|plus|or more)?\s*(?:(?:-|–|to|a)\s*(?P<ar>{_NUM})\s*(?P<arp>\+)?\s*)?"
    r"(?:years?|yrs?|anos)\b(?P<aor>\s*or more)?(?:'|’)?"
    r"[^.\n;]{0,60}?(?:experience|experiência|exp\b|background|working|professional|hands-on|commercial|"
    r"(?:software|backend|python) (?:development|engineering)|in (?:software|backend|python|a similar))|"
    rf"(?:experience|experiência)[^.\n;]{{0,40}}?(?P<bmin>at least|minimum(?: of)?|min\.?|over|more than)?\s*"
    rf"(?P<b>{_NUM})\s*(?P<bp>\+)?\s*(?:(?:-|–|to)\s*(?P<br>{_NUM})\s*)?(?:years?|yrs?|anos)", re.I)
_AT_LEAST = re.compile(r"(at least|minimum(?: of)?|min\.?|over|more than|no less than|pelo menos|m[ií]nimo de)\s*$", re.I)
_TITLE_SENIOR = re.compile(r"\b(senior|s[eé]nior|sr\.?|lead|staff|principal|head|architect|manager|expert|iii|iv)\b", re.I)
_TITLE_JUNIOR = re.compile(r"\b(junior|j[uú]nior|jr\.?|graduate|entry|trainee|intern(ship)?|est[aá]gi\w*|mid|"
                           r"intermediate|associate|ii)\b", re.I)


def _num(raw: str | None) -> int | None:
    if not raw:
        return None
    raw = raw.lower()
    return int(raw) if raw.isdigit() else _WORDS.get(raw.replace("ê", "e"))


def years_asked(desc: str) -> tuple[int, int | None] | None:
    """The strictest years-of-experience requirement in a description as (min, max), max None when
    open-ended ("3+", "at least 3"). None if it states none."""
    found = []
    for m in _YEARS.finditer(desc or ""):
        g = m.groupdict()
        lo = _num(g["a"] or g["b"])
        if not lo or lo > 15:  # bigger numbers are company history ("20 years of serving clients")
            continue
        hi = _num(g["ar"] or g["br"])
        before = (desc[max(0, m.start() - 20):m.start()])
        open_ended = bool(g["ap"] or g["arp"] or g["aor"] or g["bp"] or g["bmin"] or _AT_LEAST.search(before))
        found.append((lo, None if open_ended else (hi or lo)))
    # Strictest = the one that needs the most experience; open-ended beats a closed range with the same minimum.
    return max(found, key=lambda r: (r[0], r[1] is None, r[1] or 0)) if found else None


def _years_text(req: tuple[int, int | None]) -> str:
    lo, hi = req
    return f"asks {lo}+ years" if hi is None else f"asks {lo} years" if hi == lo else f"asks {lo}-{hi} years"


def _years_points(short: int) -> int:
    """Points for a posting's minimum years against yours: short = how many years you're missing."""
    return 8 if short <= 0 else {1: -4, 2: -14, 3: -24}.get(short, -32)


def _is_senior(req: tuple[int, int | None]) -> bool:
    lo, hi = req
    return lo >= 4 or (lo == 3 and (hi is None or hi > 3))


def seniority(title: str, desc: str) -> tuple[str | None, str]:
    """("junior-mid" | "senior" | None, why). Title words win; otherwise the years the posting asks for."""
    senior, junior = _TITLE_SENIOR.search(title or ""), _TITLE_JUNIOR.search(title or "")
    years = years_asked(desc)
    asks = _years_text(years) if years else ""
    if senior and not junior:
        return "senior", f"title: {senior.group(0)}" + (f", {asks}" if asks else "")
    if junior and not senior:
        return "junior-mid", f"title: {junior.group(0)}" + (f", {asks}" if asks else "")
    if years:  # no title word, or both ("Mid/Senior"): go by the years
        return ("senior" if _is_senior(years) else "junior-mid"), asks
    if senior:
        return "senior", f"title: {senior.group(0)}"
    return None, ""


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
        loc = p["location_match"]
        self.home = loc["home"]
        self.country = loc["country"]
        self.other_onsite = loc["other_ok_onsite"]
        self.remote_wanted = loc["remote"]
        self.remote_ok = loc["remote_ok"]
        self.remote_reject = loc["remote_reject"]
        self.city, self.country_name, self.places = p["home_city"], p["country"], p["country_places"]
        self.must_have = [s.lower() for s in p.get("must_have") or []]
        self.excluded_companies = {s.lower() for s in p.get("exclude_companies", [])}
        self.my_years = p.get("experience_years", 1)

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
        if desc and self.must_have and not any(has_term(desc, w) or has_term(title, w) for w in self.must_have):
            score -= 15
            reasons.append(f"no {' / '.join(self.must_have)} mentioned")
        if not desc:
            reasons.append("no description yet")

        years = years_asked(desc)
        if years:
            pts = _years_points(years[0] - self.my_years)
            score += pts
            reasons.append(f"{_years_text(years)}, you have {self.my_years}: {pts:+d}")

        flagged: set[str] = set()
        for rx, pts, why in self.red_flags:
            if why not in flagged and rx.search(desc):
                flagged.add(why)
                score -= pts
                reasons.append(f"-{why}")

        return max(0, min(100, score)), reasons, None

    def remote_check(self, job: sqlite3.Row | dict) -> bool:
        """True when the posting doesn't say whether it hires someone living where you do: ask before applying."""
        title, desc, location = ((job[k] or "").lower() for k in ("title", "description", "location"))
        return self._location(job, title, location, desc)[3]

    # Returns (ok, points, reason, check). You don't plan to move, so a posting is only ok if you can do it from
    # home: your city's area (any mode), remote from your country, or remote open to Europe.
    # `check` marks postings that don't say whether they hire from your country.
    def _location(self, job, title: str, location: str, desc: str) -> tuple[bool, int, str, bool]:
        ok, pts, reason, check = self._where(job, title, location, desc)
        if not ok or not desc or any(has_term(location, w) for w in self.home):
            return ok, pts, reason, check
        # Listed in a city you don't live in (another country, or elsewhere in yours): hybrid means commuting there.
        found = countries(job["location"])
        abroad = found[0] not in (REMOTE_NO_COUNTRY, UNKNOWN_COUNTRY) and self.country_name not in found
        elsewhere = any(has_term(ascii_lower(location), p) for p in self.places)
        if abroad or elsewhere:
            office = OFFICE_DAYS.search(desc) or HYBRID.search(desc)
            if office and not REMOTE_TOO.search(desc):
                return False, 0, f"hybrid / office days in {location[:40]}", False
            if office:
                return ok, pts - 4, f"{reason}; mentions hybrid (check it can be fully remote)", True
        return ok, pts, reason, check

    def _where(self, job, title: str, location: str, desc: str) -> tuple[bool, int, str, bool]:
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
            return True, 10, f"{self.city} area", False
        if in_country:
            if remote:
                return True, 6, f"{self.country_name} remote", False
            place = ascii_lower(location)
            elsewhere = [p for p in self.places if has_term(place, p)]
            if elsewhere:
                return False, 0, f"on-site/hybrid outside {self.city}: {location[:40]}", False
            return True, 2, f"{self.country_name} (city not given)", True
        if any(has_term(location, w) for w in self.other_onsite):
            return True, 0, "acceptable city", False
        if remote and not self.remote_wanted:
            return False, 0, "remote abroad (you only want local roles)", False
        if remote:
            lives_there = _residency_elsewhere(desc, self.country_name)
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
                return True, -8 if not desc else -4, f"remote, listed in {where} (check they hire from {self.country_name or 'your country'})", True
            return True, 0, "remote (region unclear)", True
        if not location.strip():
            return True, -5, "location unknown", True
        return False, 0, f"on-site: {location[:40]}", False


def _residency_elsewhere(desc: str, country: str) -> bool:
    m = RESIDENCY.search(desc)
    return bool(m) and not (country and country.lower() in desc[m.start():m.end() + 80])


def rescore_all(conn: sqlite3.Connection, scorer: Scorer | None = None) -> int:
    scorer = scorer or Scorer()
    rows = conn.execute("SELECT id, company, title, description, location, remote FROM jobs").fetchall()
    for r in rows:
        s, reasons, rejected = scorer.score(r)
        level, level_why = seniority(r["title"], r["description"])
        conn.execute(
            """UPDATE jobs SET score = ?, reasons = ?, rejected = ?, remote_check = ?, seniority = ?, seniority_why = ?
               WHERE id = ?""",
            (s, json.dumps(reasons), rejected, int(rejected is None and scorer.remote_check(r)), level, level_why,
             r["id"]),
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
