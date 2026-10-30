"""Startup job boards: Wellfound (ex-AngelList Talent) and Y Combinator's job board.

Both are read from their public, logged-out pages (the data is embedded as JSON). Throttled, capped,
and they stop quietly if the site starts refusing requests.
"""

from __future__ import annotations

import html
import json
import random
import re
import time
from collections.abc import Iterator

from ..core import Http, Job, log, ts_to_iso
from ..scoring import is_engineering_title

SIZES = {  # Wellfound size buckets -> rough headcount ceiling
    "SIZE_1_10": 10, "SIZE_11_50": 50, "SIZE_51_200": 200, "SIZE_201_500": 500,
    "SIZE_501_1000": 1000, "SIZE_1001_5000": 5000, "SIZE_5000_PLUS": 100000,
}


def _pause() -> None:
    time.sleep(random.uniform(2.0, 4.0))


def _wellfound_page(http: Http, url: str) -> tuple[dict, int] | None:
    r = http.get(url, retries=0)
    if r is None or r.status_code != 200:
        return None
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))["props"]["pageProps"]["apolloState"]["data"]
    except (KeyError, ValueError):
        return None
    pages = max((v.get("pageCount") or 1 for v in data.get("ROOT_QUERY", {}).values() if isinstance(v, dict)),
                default=1)
    return data, pages


def wellfound(http: Http, profile: dict) -> Iterator[Job]:
    cfg = profile.get("wellfound") or {}
    if not cfg.get("enabled"):
        return
    seen: set[str] = set()
    for path in cfg.get("pages", []):
        page, pages = 1, 1
        while page <= min(pages, cfg.get("max_pages", 4)):
            got = _wellfound_page(http, f"https://wellfound.com/{path}" + (f"?page={page}" if page > 1 else ""))
            _pause()
            if got is None:
                if page == 1:
                    log.info("  wellfound: %s unavailable, skipping", path)
                break
            data, pages = got
            for st in (v for v in data.values() if v.get("__typename") == "StartupResult"):
                size = st.get("companySize") or ""
                badges = [data.get(b["__ref"], {}).get("label", "") for b in st.get("badges") or []
                          if isinstance(b, dict) and "__ref" in b]
                stage = next((b for b in badges if re.search(r"seed|series|stage|early|growth|acquired|public", b, re.I)), "")
                meta = {"startup": SIZES.get(size, 0) <= 500 and "public" not in stage.lower(),
                        "size": size.replace("SIZE_", "").replace("_", "-").lower(),
                        "stage": stage, "blurb": st.get("highConcept") or ""}
                for ref in st.get("highlightedJobListings") or []:
                    j = data.get(ref.get("__ref", ""), {})
                    if not j or str(j.get("id")) in seen or not is_engineering_title(j.get("title", "")):
                        continue
                    seen.add(str(j["id"]))
                    accepted = j.get("acceptedRemoteLocationNames") or []
                    if j.get("remote"):
                        location = "Remote" + (f": {', '.join(accepted[:4])}" if accepted else "")
                    else:
                        location = ", ".join(j.get("locationNames") or [])
                    yield Job(
                        source="wellfound", ext_id=str(j["id"]), company=st.get("name", ""), title=j["title"],
                        url=f"https://wellfound.com/jobs/{j['id']}-{j.get('slug', '')}", location=location,
                        remote=True if j.get("remote") else None,
                        description=f"{meta['blurb']}\n\n{j.get('description') or ''}".strip(),
                        salary=j.get("compensation") or "", posted_at=ts_to_iso(j.get("liveStartAt")),
                        company_meta=meta,
                    )
            page += 1


def yc_jobs(http: Http, profile: dict) -> Iterator[Job]:
    cfg = profile.get("yc_jobs") or {}
    if not cfg.get("enabled"):
        return
    for path in cfg.get("pages", []):
        r = http.get(f"https://www.ycombinator.com/{path}", retries=0)
        _pause()
        if r is None or r.status_code != 200:
            continue
        m = re.search(r'data-page="([^"]+)"', r.text)
        if not m:
            continue
        try:
            postings = json.loads(html.unescape(m.group(1)))["props"].get("jobPostings") or []
        except (KeyError, ValueError):
            continue
        for j in postings:
            if not is_engineering_title(j.get("title", "")):
                continue
            facts = [j.get("companyOneLiner", ""), f"Type: {j.get('roleSpecificType', '')}",
                     f"Skills: {', '.join(j.get('skills') or [])}", f"Experience: {j.get('minExperience') or 'any'}",
                     f"Visa: {j.get('visa') or ''}", f"Salary: {j.get('salaryRange') or ''}"]
            yield Job(
                source="yc", ext_id=str(j["id"]), company=j.get("companyName", ""), title=j["title"],
                url=f"https://www.ycombinator.com{j.get('url', '')}", location=j.get("location", ""),
                remote=True if "remote" in (j.get("location") or "").lower() else None,
                description="\n".join(f for f in facts if f and not f.endswith(": ")),
                salary=j.get("salaryRange") or "",
                company_meta={"startup": True, "stage": f"YC {j.get('companyBatchName', '')}".strip(),
                              "blurb": j.get("companyOneLiner") or ""},
            )
