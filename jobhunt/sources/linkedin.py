"""LinkedIn's public (logged-out) job search pages.

No login and no account involved, so nothing can get your profile restricted. Requests are spaced out
(3–6 s). LinkedIn answers 429 now and then even at that pace, and the block clears within seconds to
minutes, so on a 429 we wait (15 s, doubling up to 5 min) and retry the same request. We only give up
for this run after ~30 minutes of 429s in a row.

Each run searches back to when the last complete run (one that finished every search) started, plus
an hour of overlap, and at most 30 days. Fetch daily and it only asks for the last ~day; a run that was
cut short, or a few days without fetching, doesn't leave a gap. Postings already known are never
fetched again, so the overlap only costs a page or two of search results.
"""

from __future__ import annotations

import json
import random
import re
import time
from collections.abc import Iterator

from bs4 import BeautifulSoup

from ..core import CANCEL, DATA, Http, Job, check_cancel, html_to_text, log

SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"


STATE = DATA / "linkedin_state.json"  # when the last complete LinkedIn search finished
MAX_WINDOW = 30 * 86400                # LinkedIn's "posted in the last N seconds" filter, at most 30 days
OVERLAP = 3600                         # LinkedIn can list a posting a little after its posted time
BACKOFF = [15, 30, 60, 120, 240, 300, 300, 300, 300, 300]  # waits after consecutive 429s (~33 min total)


class RateLimited(Exception):
    pass


def _sleep(seconds: float) -> None:
    """Sleep, but wake up at once if the fetch is cancelled."""
    CANCEL.wait(seconds)
    check_cancel()


def _pause() -> None:
    _sleep(random.uniform(3.0, 6.0))


def _request(http: Http, url: str, **params):
    """GET with patient 429 handling. Raises RateLimited only after the whole BACKOFF schedule."""
    for wait in [*BACKOFF, None]:
        r = http.get(url, params=params or None, retries=0)
        if r is None or r.status_code != 429:
            return r
        if wait is None:
            raise RateLimited
        retry_after = r.headers.get("Retry-After", "")
        wait = max(wait, int(retry_after)) if retry_after.isdigit() else wait
        log.info("  linkedin: rate-limited, waiting %d s and trying again", wait)
        _sleep(wait + random.uniform(0, 5))
    raise RateLimited  # not reached


def _get(http: Http, url: str, **params) -> str | None:
    r = _request(http, url, **params)
    if r is None:
        return None
    return r.text if r.status_code == 200 else None


def _window() -> int:
    """Seconds to look back: since the last complete run started, plus OVERLAP, 30 days at most."""
    try:
        last = json.loads(STATE.read_text())["last_complete"]
    except (OSError, ValueError, KeyError, TypeError):
        return MAX_WINDOW
    return int(min(MAX_WINDOW, max(OVERLAP, time.time() - last + OVERLAP)))


def _mark_complete(started: float) -> None:
    """Record when this run *started*: postings published while it ran are picked up next time."""
    STATE.write_text(json.dumps({"last_complete": started}))


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
    r = _request(http, DETAIL.format(id=job_id))
    if r is None:
        return None
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
    started = time.time()
    seconds = MAX_WINDOW if first_run else _window()
    window = f"r{seconds}"
    log.info("  linkedin: postings from the last %s", f"{seconds / 86400:.1f} days" if seconds >= 2 * 86400
             else f"{seconds / 3600:.0f} hours")
    detail_budget = cfg.get("max_detail_fetches")  # None = no limit
    seen: set[str] = set()
    try:
        for search in cfg.get("searches", []):
            log.info("  linkedin: searching \"%s\" in %s%s", search["keywords"], search["location"],
                     " (remote)" if search.get("remote") else "")
            for start in range(0, 1000, 10):  # the public search stops serving results at ~1000
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
                    if c["id"] not in known and (detail_budget is None or detail_budget > 0) and wants_detail({**c, "remote": search.get("remote")}):
                        desc, criteria = _detail(http, c["id"])
                        if detail_budget is not None:
                            detail_budget -= 1
                        _pause()
                    yield Job(
                        source="linkedin", ext_id=c["id"], company=c["company"], title=c["title"],
                        url=f"https://www.linkedin.com/jobs/view/{c['id']}/", location=c["location"],
                        remote=True if search.get("remote") else None,
                        description=(desc + ("\n\n" + "\n".join(criteria) if criteria else "")).strip(),
                        tags=criteria, posted_at=c["posted"],
                    )
        _mark_complete(started)
    except RateLimited:
        log.warning("LinkedIn kept rate-limiting us for ~30 minutes; stopping LinkedIn for this run (results so far "
                    "are kept, and the next run searches back to the last complete one).")


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
