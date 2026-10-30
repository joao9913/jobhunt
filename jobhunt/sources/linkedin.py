"""LinkedIn's public (logged-out) job search pages.

No login and no account involved, so nothing can get your profile restricted. Requests are spaced out
and capped; if LinkedIn answers 429 we stop for this run.
"""

from __future__ import annotations

import random
import re
import time
from collections.abc import Iterator

from bs4 import BeautifulSoup

from ..core import Http, Job, html_to_text, log

SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"


class RateLimited(Exception):
    pass


def _pause() -> None:
    time.sleep(random.uniform(1.5, 3.5))


def _get(http: Http, url: str, **params) -> str | None:
    r = http.get(url, params=params, retries=0)
    if r is None:
        return None
    if r.status_code == 429:
        raise RateLimited
    return r.text if r.status_code == 200 else None


def _cards(page: str) -> list[dict]:
    soup = BeautifulSoup(page, "html.parser")
    out = []
    for card in soup.select("div.base-search-card"):
        urn = card.get("data-entity-urn", "")
        m = re.search(r"(\d+)$", urn)
        if not m:
            continue
        title = card.select_one(".base-search-card__title")
        company = card.select_one(".base-search-card__subtitle")
        loc = card.select_one(".job-search-card__location")
        when = card.select_one("time")
        out.append({
            "id": m.group(1),
            "title": title.get_text(strip=True) if title else "",
            "company": company.get_text(strip=True) if company else "",
            "location": loc.get_text(strip=True) if loc else "",
            "posted": when.get("datetime") if when else None,
        })
    return out


def _detail(http: Http, job_id: str) -> tuple[str, list[str]]:
    page = _get(http, DETAIL.format(id=job_id))
    if not page:
        return "", []
    soup = BeautifulSoup(page, "html.parser")
    desc = soup.select_one(".description__text--rich, .show-more-less-html__markup")
    criteria = [
        f"{li.select_one('h3').get_text(strip=True)}: {li.select_one('span').get_text(strip=True)}"
        for li in soup.select(".description__job-criteria-item")
        if li.select_one("h3") and li.select_one("span")
    ]
    return (html_to_text(str(desc)) if desc else ""), criteria


def is_closed(http: Http, job_id: str) -> bool | None:
    """True when the posting no longer takes applications (or was taken down), None if we couldn't tell."""
    r = http.get(DETAIL.format(id=job_id), retries=0)
    if r is None:
        return None
    if r.status_code == 429:
        raise RateLimited
    if r.status_code in (404, 410):
        return True
    if r.status_code != 200:
        return None
    return "closed-job" in r.text or "no longer accepting applications" in r.text.lower()


def check_closed(http: Http, job_ids: list[str]) -> Iterator[tuple[str, bool | None]]:
    """Re-check postings we already have. Throttled like everything else; stops on 429."""
    try:
        for job_id in job_ids:
            yield job_id, is_closed(http, job_id)
            _pause()
    except RateLimited:
        log.warning("LinkedIn rate-limited us while checking for closed postings; continuing next run.")


def linkedin(http: Http, profile: dict, *, known: set[str], wants_detail, first_run: bool) -> Iterator[Job]:
    cfg = profile.get("linkedin") or {}
    if not cfg.get("enabled"):
        return
    window = "r604800" if first_run else "r172800"  # past week on first run, then past 2 days
    detail_budget = cfg.get("max_detail_fetches", 80)
    seen: set[str] = set()
    try:
        for search in cfg.get("searches", []):
            for start in range(0, 200, 10):
                params = {"keywords": search["keywords"], "location": search["location"], "f_TPR": window,
                          "start": start}
                if search.get("remote"):
                    params["f_WT"] = "2"
                page = _get(http, SEARCH, **params)
                _pause()
                cards = _cards(page or "")
                if not cards:
                    break
                for c in cards:
                    if c["id"] in seen:
                        continue
                    seen.add(c["id"])
                    desc, criteria = "", []
                    if c["id"] not in known and detail_budget > 0 and wants_detail({**c, "remote": search.get("remote")}):
                        desc, criteria = _detail(http, c["id"])
                        detail_budget -= 1
                        _pause()
                    yield Job(
                        source="linkedin", ext_id=c["id"], company=c["company"], title=c["title"],
                        url=f"https://www.linkedin.com/jobs/view/{c['id']}/", location=c["location"],
                        remote=True if search.get("remote") else None,
                        description=(desc + ("\n\n" + "\n".join(criteria) if criteria else "")).strip(),
                        tags=criteria, posted_at=c["posted"],
                    )
    except RateLimited:
        log.warning("LinkedIn rate-limited us; stopping LinkedIn for this run (results so far are kept).")


def backfill(http: Http, job_ids: list[str], budget: int) -> Iterator[tuple[str, str]]:
    """Fetch descriptions for postings we already know but couldn't read yet."""
    try:
        for job_id in job_ids[:budget]:
            desc, criteria = _detail(http, job_id)
            _pause()
            if desc:
                yield job_id, (desc + ("\n\n" + "\n".join(criteria) if criteria else "")).strip()
    except RateLimited:
        log.warning("LinkedIn rate-limited us during backfill; continuing next run.")
