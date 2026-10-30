"""Aggregator job boards with public APIs."""

from __future__ import annotations

import re
from collections.abc import Iterator

from ..core import Http, Job, html_to_text, iso_date, ts_to_iso
from ..scoring import is_engineering_title


def landing_jobs(http: Http, profile: dict) -> Iterator[Job]:
    """Portugal-focused tech board."""
    offset = 0
    while offset < 3000:
        data = http.json("https://landing.jobs/api/v1/jobs", params={"limit": 50, "offset": offset})
        if not data:
            break
        for j in data:
            if not is_engineering_title(j.get("title", "")):
                continue
            m = re.search(r"/at/([^/]+)/", j.get("url", ""))
            company = m.group(1).replace("-", " ").title() if m else "Unknown"
            locs = ", ".join(f"{x.get('city')}, {x.get('country_code')}" for x in j.get("locations") or [])
            salary = ""
            if j.get("gross_salary_low"):
                salary = f"{j['gross_salary_low']}–{j.get('gross_salary_high') or '?'} {j.get('currency_code', '')}"
            yield Job(
                source="landingjobs", ext_id=str(j["id"]), company=company, title=j["title"], url=j["url"],
                location=locs or ("Remote" if j.get("remote") else ""), remote=bool(j.get("remote")) or None,
                description=html_to_text(
                    f"{j.get('role_description', '')}{j.get('main_requirements', '')}{j.get('nice_to_have', '')}"
                ),
                tags=j.get("tags") or [], salary=salary, posted_at=iso_date(j.get("published_at")),
            )
        offset += len(data)


def remotive(http: Http, profile: dict) -> Iterator[Job]:
    data = http.json("https://remotive.com/api/remote-jobs", params={"category": profile.get("remotive_category")})
    for j in (data or {}).get("jobs", []):
        yield Job(
            source="remotive", ext_id=str(j["id"]), company=j["company_name"], title=j["title"], url=j["url"],
            location=j.get("candidate_required_location", ""), remote=True,
            description=html_to_text(j.get("description", "")), tags=j.get("tags") or [],
            salary=j.get("salary") or "", posted_at=iso_date(j.get("publication_date")),
        )


def remoteok(http: Http, profile: dict) -> Iterator[Job]:
    data = http.json("https://remoteok.com/api")
    for j in (data or [])[1:]:  # first item is a legal notice
        if not isinstance(j, dict) or not j.get("position"):
            continue
        if not is_engineering_title(j["position"]):
            continue
        salary = f"{j['salary_min']}–{j['salary_max']} USD" if j.get("salary_min") else ""
        yield Job(
            source="remoteok", ext_id=str(j["id"]), company=j.get("company", ""), title=j["position"],
            url=j.get("url", ""), location=j.get("location") or "", remote=True,
            description=html_to_text(j.get("description", "")), tags=j.get("tags") or [], salary=salary,
            posted_at=iso_date(j.get("date")),
        )


def arbeitnow(http: Http, profile: dict) -> Iterator[Job]:
    url = "https://www.arbeitnow.com/api/job-board-api"
    for _ in range(5):
        data = http.json(url)
        if not data:
            break
        for j in data.get("data", []):
            if not is_engineering_title(j["title"]):
                continue
            yield Job(
                source="arbeitnow", ext_id=j["slug"], company=j["company_name"], title=j["title"], url=j["url"],
                location=j.get("location", ""), remote=bool(j.get("remote")) or None,
                description=html_to_text(j.get("description", "")), tags=j.get("tags") or [],
                posted_at=ts_to_iso(j.get("created_at")),
            )
        url = (data.get("links") or {}).get("next")
        if not url:
            break


def himalayas(http: Http, profile: dict) -> Iterator[Job]:
    """Remote-only board; searched for jobs open to people in Portugal."""
    for q in profile.get("himalayas_queries", []):
        for page in range(1, 6):
            data = http.json("https://himalayas.app/jobs/api/search", params={"q": q, "country": "Portugal", "page": page})
            jobs = (data or {}).get("jobs", [])
            for j in jobs:
                if not is_engineering_title(j["title"]):
                    continue
                restr = j.get("locationRestrictions") or []
                loc = "Remote, Europe" if "Portugal" in restr else ("Remote, worldwide" if not restr else ", ".join(restr[:4]))
                salary = ""
                if j.get("minSalary"):
                    salary = f"{j['minSalary']}–{j.get('maxSalary') or '?'} {j.get('currency', '')}/{j.get('salaryPeriod', 'yr')}"
                yield Job(
                    source="himalayas", ext_id=j.get("guid") or j["applicationLink"], company=j["companyName"],
                    title=j["title"], url=j["applicationLink"], location=loc, remote=True,
                    description=html_to_text(j.get("description", "")), salary=salary,
                    tags=j.get("categories") or [], posted_at=ts_to_iso(j.get("pubDate")),
                )
            if len(jobs) < 20:
                break


def hn_whos_hiring(http: Http, profile: dict) -> Iterator[Job]:
    """Monthly 'Ask HN: Who is hiring?' thread. Keeps only posts that look remote-EU or Portugal + Python."""
    if not profile.get("hn_whos_hiring"):
        return
    hits = (http.json(
        "https://hn.algolia.com/api/v1/search_by_date",
        params={"tags": "story,author_whoishiring", "hitsPerPage": 5},
    ) or {}).get("hits", [])
    story = next((h for h in hits if h.get("title", "").lower().startswith("ask hn: who is hiring")), None)
    if not story:
        return
    item = http.json(f"https://hn.algolia.com/api/v1/items/{story['objectID']}")
    for c in (item or {}).get("children", []):
        text = html_to_text(c.get("text") or "")
        low = text.lower()
        if "python" not in low:
            continue
        if not re.search(r"remote[^.\n]{0,40}(europe|eu\b|emea|worldwide|anywhere|cet|gmt)|portugal|lisbon", low):
            continue
        first = text.split("\n", 1)[0]
        parts = [p.strip() for p in first.split("|")]
        company = parts[0][:80] if parts else "Unknown"
        title = next((p for p in parts[1:] if re.search(r"engineer|developer|backend|python", p, re.I)), "Engineer (see post)")
        location = next((p for p in parts[1:] if re.search(r"remote|europe|lisbon|portugal|onsite|hybrid", p, re.I)), "")
        yield Job(
            source="hn", ext_id=str(c["id"]), company=company, title=title[:120],
            url=f"https://news.ycombinator.com/item?id={c['id']}", location=location[:120],
            remote=True if "remote" in location.lower() else None, description=text,
            posted_at=iso_date(c.get("created_at")),
        )


from .startups import wellfound, yc_jobs  # noqa: E402

BOARDS = {
    "wellfound": wellfound,
    "yc": yc_jobs,
    "landingjobs": landing_jobs,
    "remotive": remotive,
    "remoteok": remoteok,
    "arbeitnow": arbeitnow,
    "himalayas": himalayas,
    "hn": hn_whos_hiring,
}
