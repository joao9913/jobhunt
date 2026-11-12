"""Portuguese general job boards, for fields the tech boards don't cover (psychology...).

Net-Empregos: the biggest general board in Portugal. Its public search pages are plain HTML (no login, no API):
up to 100 results per search, ~18 per page. Descriptions need one request per posting, so a posting is only
opened when we haven't read it yet and its title and place already pass your profile, a few seconds apart.
Too many requests in a short time and the site answers with a login page and a captcha for a while (seen
2026-11-12 after ~300 requests in a few minutes); we stop for this run when that happens.
"""

from __future__ import annotations

import random
import re
import time
from collections.abc import Iterator

from bs4 import BeautifulSoup

from ..core import Http, Job, check_cancel, fold, html_to_text, log
from ..scoring import is_relevant_title

NET = "https://www.net-empregos.com"


class Blocked(Exception):
    pass


def _text(r) -> str:
    """Net-Empregos doesn't declare a charset; its pages are Windows-1252 (some newer ones UTF-8)."""
    try:
        return r.content.decode("utf-8")
    except UnicodeDecodeError:
        return r.content.decode("cp1252", "replace")


def _iso(ddmmyyyy: str) -> str | None:
    m = re.match(r"(\d{2})-(\d{2})-(\d{4})", ddmmyyyy.strip())
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def _cards(page: str) -> list[dict]:
    soup = BeautifulSoup(page, "html.parser")
    out = []
    for item in soup.select("div.job-item"):
        link = item.select_one("h2 a.oferta-link")
        m = re.match(r"/(\d+)/", (link.get("href") or "") if link else "")
        if not m:
            continue
        info = {"date": "", "place": "", "category": "", "company": ""}
        for li in item.select(".job-ad-item li"):
            icon = " ".join((li.select_one("i") or {}).get("class") or [])
            text = li.get_text(" ", strip=True)
            key = ("date" if "calendar" in icon else "place" if "pin" in icon else "category" if "tags" in icon
                   else "company" if "work" in icon else None)
            if key:
                info[key] = text
        out.append({"id": m.group(1), "title": link.get_text(" ", strip=True), "url": NET + link["href"], **info})
    return out


def _page(http: Http, url: str, **params) -> str | None:
    r = http.get(url, params=params or None, retries=1)
    if r is None or r.status_code != 200:
        return None
    text = _text(r)
    title = re.search(r"<title>([^<]*)</title>", text[:5000], re.I)
    if title and "login" in title.group(1).lower():  # "Net-Empregos - Login de Candidato" + captcha
        raise Blocked
    return text


def _detail(http: Http, url: str) -> str:
    page = _page(http, url)
    if page is None:
        return ""
    soup = BeautifulSoup(page, "html.parser")
    head = next((h for h in soup.find_all("h2") if "Detalhe da Oferta" in h.get_text()), None)
    body = head.find_next("div", style=re.compile(r"font-size:\s*20px")) if head else None
    if body is None:
        return ""
    for junk in body.select("#responseDiv"):
        junk.decompose()
    return html_to_text(str(body))


def netempregos(http: Http, profile: dict) -> Iterator[Job]:
    from .. import db
    from ..scoring import Scorer

    # Its search only understands plain ASCII: "psicólogo" finds nothing, "psicologo" finds both spellings.
    terms = list(dict.fromkeys(fold(t).strip() for t in profile.get("search_terms_used") or [] if t.strip()))
    scorer = Scorer(profile)
    conn = db.connect()
    try:
        known = db.known_ext_ids(conn, "netempregos")
    finally:
        conn.close()
    seen: set[str] = set()
    try:
        for term in terms:
            for page_no in range(1, 7):
                page = _page(http, f"{NET}/pesquisa-empregos.asp", chaves=term, page=page_no)
                if page is None:
                    log.info("  netempregos: search \"%s\" unavailable, skipping", term)
                    break
                cards = _cards(page)
                for c in cards:
                    if c["id"] in seen or not is_relevant_title(c["title"]):
                        continue
                    seen.add(c["id"])
                    # "( Todas as zonas )": anywhere in the country, the posting doesn't pick a place.
                    place = "Portugal" if "todas as zonas" in fold(c["place"]) else c["place"]
                    card = {"company": c["company"], "title": c["title"], "location": place, "remote": None,
                            "description": ""}
                    desc = ""
                    if c["id"] not in known and scorer.score(card)[2] is None:
                        check_cancel()
                        time.sleep(random.uniform(3.0, 6.0))
                        desc = _detail(http, c["url"])
                    if c["category"]:
                        desc = f"{desc}\n\nCategoria: {c['category']}".strip()
                    yield Job(
                        source="netempregos", ext_id=c["id"], company=c["company"] or "Unknown", title=c["title"],
                        url=c["url"], location=place, remote=None, description=desc, posted_at=_iso(c["date"]),
                    )
                if len(cards) < 10:
                    break
                time.sleep(random.uniform(2.0, 4.0))
    except Blocked:
        log.warning("  netempregos: the site is asking for a login / captcha (too many requests from this address); "
                    "skipping it for this run, it usually clears within hours")
