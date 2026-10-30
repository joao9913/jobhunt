"""Public job-board APIs that companies use for their careers pages. No auth, no scraping."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator

from ..core import Http, Job, html_to_text, iso_date, ts_to_iso
from ..scoring import is_engineering_title


def greenhouse(http: Http, slug: str, company: str) -> Iterator[Job]:
    data = http.json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", params={"content": "true"})
    for j in (data or {}).get("jobs", []):
        if not is_engineering_title(j["title"]):
            continue
        yield Job(
            source="greenhouse", ext_id=f"{slug}:{j['id']}", company=company, title=j["title"],
            url=j.get("absolute_url", ""), location=(j.get("location") or {}).get("name", ""),
            description=html_to_text(j.get("content", "")), posted_at=iso_date(j.get("updated_at")),
        )


def lever(http: Http, slug: str, company: str) -> Iterator[Job]:
    data = None
    for host in ("api.lever.co", "api.eu.lever.co"):
        data = http.json(f"https://{host}/v0/postings/{slug}", params={"mode": "json"})
        if data:
            break
    for j in data or []:
        if not is_engineering_title(j.get("text", "")):
            continue
        cats = j.get("categories") or {}
        lists = "\n".join(f"{x.get('text', '')}\n{html_to_text(x.get('content', ''))}" for x in j.get("lists", []))
        yield Job(
            source="lever", ext_id=f"{slug}:{j['id']}", company=company, title=j["text"],
            url=j.get("hostedUrl", ""),
            location=", ".join(filter(None, [cats.get("location"), *(cats.get("allLocations") or [])][:3])),
            remote=True if j.get("workplaceType") == "remote" else None,
            description=f"{j.get('descriptionPlain', '')}\n{lists}\n{j.get('additionalPlain', '')}",
            posted_at=ts_to_iso(j.get("createdAt")),
        )


def ashby(http: Http, slug: str, company: str) -> Iterator[Job]:
    data = http.json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    for j in (data or {}).get("jobs", []):
        if not is_engineering_title(j["title"]) or j.get("isListed") is False:
            continue
        locs = [j.get("location", "")] + [s.get("location", "") for s in j.get("secondaryLocations") or []]
        yield Job(
            source="ashby", ext_id=f"{slug}:{j['id']}", company=company, title=j["title"],
            url=j.get("jobUrl", ""), location=", ".join(filter(None, locs))[:200],
            remote=True if j.get("isRemote") or j.get("workplaceType") == "Remote" else None,
            description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml", "")),
            posted_at=iso_date(j.get("publishedAt")),
        )


def smartrecruiters(http: Http, slug: str, company: str) -> Iterator[Job]:
    offset, details = 0, 0
    while offset < 1000:
        data = http.json(
            f"https://api.smartrecruiters.com/v1/companies/{slug}/postings",
            params={"limit": 100, "offset": offset},
        )
        content = (data or {}).get("content", [])
        for j in content:
            if not is_engineering_title(j["name"]):
                continue
            loc = j.get("location") or {}
            desc = ""
            # Descriptions need one call per posting; only for plausible ones, capped.
            country = (loc.get("country") or "").lower()
            if details < 40 and (country == "pt" or loc.get("remote")):
                d = http.json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{j['id']}")
                secs = ((d or {}).get("jobAd") or {}).get("sections") or {}
                desc = "\n".join(html_to_text((s or {}).get("text", "")) for s in secs.values())
                details += 1
            yield Job(
                source="smartrecruiters", ext_id=f"{slug}:{j['id']}", company=company, title=j["name"],
                url=f"https://jobs.smartrecruiters.com/{slug}/{j['id']}",
                location=loc.get("fullLocation", ""), remote=bool(loc.get("remote")) or None,
                description=desc, posted_at=iso_date(j.get("releasedDate")),
            )
        if len(content) < 100:
            break
        offset += 100


def workable(http: Http, slug: str, company: str) -> Iterator[Job]:
    data = http.json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}", params={"details": "true"})
    for j in (data or {}).get("jobs", []):
        if not is_engineering_title(j.get("title", "")):
            continue
        loc = ", ".join(filter(None, [j.get("city"), j.get("state"), j.get("country")]))
        yield Job(
            source="workable", ext_id=f"{slug}:{j.get('shortcode')}", company=company, title=j["title"],
            url=j.get("url") or j.get("shortlink", ""), location=loc,
            remote=True if j.get("telecommuting") else None,
            description=html_to_text(j.get("description", "")), posted_at=iso_date(j.get("published_on")),
        )


def recruitee(http: Http, slug: str, company: str) -> Iterator[Job]:
    data = http.json(f"https://{slug}.recruitee.com/api/offers/")
    for j in (data or {}).get("offers", []):
        if not is_engineering_title(j.get("title", "")):
            continue
        yield Job(
            source="recruitee", ext_id=f"{slug}:{j['id']}", company=company, title=j["title"],
            url=j.get("careers_url", ""), location=j.get("location", ""),
            remote=True if j.get("remote") else None,
            description=html_to_text(f"{j.get('description', '')}{j.get('requirements', '')}"),
            posted_at=iso_date(j.get("published_at")),
        )


def personio(http: Http, slug: str, company: str) -> Iterator[Job]:
    for tld in ("de", "com"):
        r = http.get(f"https://{slug}.jobs.personio.{tld}/xml", params={"language": "en"})
        if r is not None and r.status_code == 200 and r.text.lstrip().startswith("<"):
            break
    else:
        return
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError:
        return
    for pos in root.iter("position"):
        title = pos.findtext("name", "")
        if not is_engineering_title(title):
            continue
        pid = pos.findtext("id", "")
        desc = "\n".join(
            f"{d.findtext('name', '')}\n{html_to_text(d.findtext('value', ''))}" for d in pos.iter("jobDescription")
        )
        yield Job(
            source="personio", ext_id=f"{slug}:{pid}", company=company, title=title,
            url=f"https://{slug}.jobs.personio.{tld}/job/{pid}", location=pos.findtext("office", ""),
            description=desc, posted_at=iso_date(pos.findtext("createdAt")),
        )


FETCHERS: dict[str, Callable[[Http, str, str], Iterator[Job]]] = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "smartrecruiters": smartrecruiters,
    "workable": workable,
    "recruitee": recruitee,
    "personio": personio,
}


# ---------- finding which ATS a company uses ----------


def _probe(http: Http, ats: str, slug: str) -> tuple[int, str | None]:
    """Return (total postings, board display name if the API exposes one); 0 when the board doesn't exist."""
    if ats == "greenhouse":
        d = http.json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", retries=0)
        if d and d.get("jobs") is not None:
            meta = http.json(f"https://boards-api.greenhouse.io/v1/boards/{slug}", retries=0) or {}
            return len(d["jobs"]), meta.get("name")
    elif ats == "lever":
        for host in ("api.lever.co", "api.eu.lever.co"):
            d = http.json(f"https://{host}/v0/postings/{slug}", params={"mode": "json", "limit": 50}, retries=0)
            if isinstance(d, list) and d:
                return len(d), None
    elif ats == "ashby":
        d = http.json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", retries=0)
        if d and d.get("jobs"):
            return len(d["jobs"]), None
    elif ats == "smartrecruiters":
        d = http.json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings", params={"limit": 1}, retries=0)
        if d and d.get("totalFound"):
            name = ((d.get("content") or [{}])[0].get("company") or {}).get("name")
            return d["totalFound"], name
    elif ats == "workable":
        d = http.json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}", retries=0)
        if d and d.get("jobs"):
            return len(d["jobs"]), d.get("name")
    elif ats == "recruitee":
        d = http.json(f"https://{slug}.recruitee.com/api/offers/", retries=0)
        if d and d.get("offers"):
            return len(d["offers"]), None
    elif ats == "personio":
        r = http.get(f"https://{slug}.jobs.personio.de/xml", retries=0)
        if r is not None and r.status_code == 200 and "<position>" in r.text:
            return r.text.count("<position>"), None
    return 0, None


def slug_candidates(name: str) -> list[str]:
    import re
    import unicodedata

    base = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    base = re.sub(r"[.+&']", " ", base)
    words = [w for w in re.split(r"[^a-z0-9]+", base) if w]
    out = ["".join(words), "-".join(words)]
    if len(words) > 1:
        out.append(words[0])
    return list(dict.fromkeys(s for s in out if len(s) >= 3))


def resolve_ats(http: Http, name: str) -> tuple[str, str] | None:
    """Find the board with the most postings among plausible slugs. Name-checked where the API allows."""
    from ..core import company_key

    best: tuple[int, str, str] | None = None
    want = company_key(name)
    candidates = slug_candidates(name)
    first_word = candidates[-1] if len(candidates) == 3 else None
    for slug in candidates:
        for ats in FETCHERS:
            count, board_name = _probe(http, ats, slug)
            if not count:
                continue
            # A bare first word ("bloom", "sanity") is risky: only accept it with a verified name match.
            if slug == first_word and (not board_name or company_key(board_name) != want):
                continue
            if best is None or count > best[0]:
                best = (count, ats, slug)
        if best:
            break  # prefer the most specific slug that hits
    return (best[1], best[2]) if best else None
