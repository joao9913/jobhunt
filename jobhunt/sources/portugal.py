"""Portuguese job boards for fields the tech boards don't cover (psychology...).

Net-Empregos: the biggest general board in Portugal. Its public search pages are plain HTML (no login, no API):
up to 100 results per search, ~18 per page. Descriptions need one request per posting, so a posting is only
opened when we haven't read it yet and its title and place already pass your profile, a few seconds apart.
Too many requests in a short time and the site answers with a login page and a captcha for a while (seen
2026-11-12 after ~300 requests in a few minutes). When that happens we stop, remember it, and skip the site for
the next BLOCK_HOURS; the dashboard offers to open the site (you solve the captcha yourself) and retry. Its search
matches every posting containing the words, so only the broadest of your searches run there ("psicologo" already
finds "psicologo clinico").

BEP (Bolsa de Emprego Público, bep.gov.pt): every public-sector job (SNS / ULS, Segurança Social, councils, Casa
Pia, universities...). An ASP.NET site: the search and each offer's details are form posts. Its search only knows
areas ("psicologia" finds offers in psychology, "psicologo" finds nothing) and lists active offers only, a few a
day, so one search and one request per offer we haven't read yet. Offers have no title; we build one from the
category and the area ("Técnico Superior (Psicologia)"). Each offer lists who may apply: when "Sem Relação
Jurídica de Emprego Público" isn't among them, only people who already work in the public sector can, and the
description says so (a red flag in fields.py).
"""

from __future__ import annotations

import json
import random
import re
import time
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

from bs4 import BeautifulSoup

from ..core import (
    USERS,
    Http,
    Job,
    check_cancel,
    data_dir,
    fold,
    html_to_text,
    log,
    multi_user,
)
from ..scoring import is_relevant_title

NET = "https://www.net-empregos.com"
BLOCK_HOURS = 12


class Blocked(Exception):
    pass


# ---------- Net-Empregos block memory ----------
# The block is on this computer's address, so it's shared by every account here.


def _block_path() -> Path:
    return (USERS if multi_user() else data_dir()) / "netempregos_block.json"


def blocked_since() -> datetime | None:
    """When Net-Empregos started asking for a captcha, if that was less than BLOCK_HOURS ago."""
    try:
        when = datetime.fromisoformat(json.loads(_block_path().read_text())["blocked_at"])
    except (OSError, ValueError, KeyError):
        return None
    return when if datetime.now() - when < timedelta(hours=BLOCK_HOURS) else None


def block_info() -> dict | None:
    """For the dashboard: since when, until when, and the page to open to solve the captcha."""
    since = blocked_since()
    if since is None:
        return None
    until = since + timedelta(hours=BLOCK_HOURS)
    return {"since": since.strftime("%H:%M"), "until": until.strftime("%d/%m %H:%M"), "url": search_url()}


def clear_block() -> None:
    _block_path().unlink(missing_ok=True)


def _mark_blocked() -> None:
    _block_path().write_text(json.dumps({"blocked_at": datetime.now().isoformat(timespec="seconds")}))


def search_url(term: str = "psicologo") -> str:
    """The search page to open in a browser to solve the captcha."""
    return f"{NET}/pesquisa-empregos.asp?chaves={fold(term).strip().replace(' ', '+')}"


def broad_terms(terms: list[str]) -> list[str]:
    """Your searches without the ones another search already covers: on a site whose search finds every posting
    containing all the words, "psicologo clinico" adds nothing to "psicologo"."""
    folded = list(dict.fromkeys(fold(t).strip() for t in terms if t.strip()))
    return [t for t in folded if not any(o != t and set(o.split()) <= set(t.split()) for o in folded)]


# ---------- Net-Empregos ----------


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

    since = blocked_since()
    if since:
        log.warning("  netempregos: asked for a captcha at %s; skipping it until %s (or solve the captcha and press "
                    "Retry Net-Empregos on the search page)", since.strftime("%H:%M"),
                    (since + timedelta(hours=BLOCK_HOURS)).strftime("%d/%m %H:%M"))
        return
    # Its search only understands plain ASCII: "psicólogo" finds nothing, "psicologo" finds both spellings.
    terms = broad_terms(profile.get("search_terms_used") or [])
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
        clear_block()
    except Blocked:
        _mark_blocked()
        log.warning("  netempregos: the site is asking for a captcha (too many requests from this address); "
                    "skipping it for %d hours. To get it back sooner, solve the captcha in your browser and press "
                    "Retry Net-Empregos on the search page", BLOCK_HOURS)


# ---------- BEP (Bolsa de Emprego Público) ----------

BEP = "https://www.bep.gov.pt/pages/oferta/"
_ASP = "ctl00$ctl00$FormMasterContentPlaceHolder$ContentPlaceHolder1$"
# Offers open to people outside the public sector list this among who may apply.
OPEN_TO_ALL = "sem relacao juridica de emprego publico"
RESTRICTED = "Restrito a trabalhadores com vínculo de emprego público."  # matched by a red flag in fields.py


def _form(soup: BeautifulSoup) -> dict:
    """The page's hidden ASP.NET state (__VIEWSTATE...), which every form post sends back."""
    return {i["name"]: i.get("value", "") for i in soup.select("input[type=hidden][name]")}


def _bep_search(http: Http, term: str) -> tuple[str, BeautifulSoup] | None:
    """The results page for a search: its URL and parsed page (50 per page)."""
    r = http.get(BEP + "Oferta_Pesquisa_basica.aspx")
    if r is None or r.status_code != 200:
        return None
    time.sleep(random.uniform(1.5, 3.0))
    data = {**_form(BeautifulSoup(r.text, "html.parser")), _ASP + "txtValor": term, _ASP + "ucSearch": "Pesquisar"}
    r = http.post_form(str(r.url), data)
    if r is None or r.status_code != 200:
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    total = re.search(r"Total de Registo\(s\):\s*(\d+)", soup.get_text(" "))
    if total and int(total.group(1)) > len(_bep_rows(soup)):  # more than the 10 a page shows: ask for 50
        time.sleep(random.uniform(1.5, 3.0))
        data = {**_form(soup), "__EVENTTARGET": _ASP + "ddlNReg", "__EVENTARGUMENT": "", _ASP + "ddlNReg": "50"}
        r2 = http.post_form(str(r.url), data)
        if r2 is not None and r2.status_code == 200:
            soup = BeautifulSoup(r2.text, "html.parser")
    return str(r.url), soup


def _bep_rows(soup: BeautifulSoup) -> list[dict]:
    rows = []
    for a in soup.select("a[id$=btnDetalhes]"):
        target = re.search(r"__doPostBack\('([^']+)'", a.get("href", "").replace("&#39;", "'"))
        tds = [td.get_text(" ", strip=True) for td in a.find_parent("tr").find_all("td")]
        if target:
            rows.append({"code": a.get_text(strip=True), "target": target.group(1), "cells": tds})
    return rows


def _bep_fields(soup: BeautifulSoup) -> dict[str, str]:
    """Every "Label: value" row of an offer's page, in order."""
    out = {}
    for label in soup.select("div.tabletitle"):
        value = label.find_next_sibling("div")
        if value is None:
            continue
        for br in value.find_all("br"):
            br.replace_with("\n")
        text = "\n".join(re.sub(r"\s+", " ", line).strip() for line in value.get_text().split("\n"))
        out[label.get_text(" ", strip=True).rstrip(":").strip()] = re.sub(r"\n+", "\n", text.strip())
    return out


def _bep_table(soup: BeautifulSoup, header: str) -> list[dict[str, str]]:
    """The rows of the small table whose header row has `header` (the work places, the subject areas)."""
    for table in soup.find_all("table"):
        cells = [td.get_text(" ", strip=True) for td in table.find("tr").find_all("td")] if table.find("tr") else []
        if header in cells:
            return [dict(zip(cells, [td.get_text(" ", strip=True) for td in tr.find_all("td")], strict=False))
                    for tr in table.find_all("tr")[1:]]
    return []


def bep_offer(html: str, url: str) -> Job | None:
    """An offer's page as a Job, or None if it isn't one."""
    soup = BeautifulSoup(html, "html.parser")
    f = _bep_fields(soup)
    code = f.get("Código da Oferta", "")
    if not code:
        return None
    places = _bep_table(soup, "Distrito")
    areas = _bep_table(soup, "Área Temática")
    area = next((a["Área Temática"] for a in areas if a.get("Área Temática") and "ignorad" not in fold(a["Área Temática"])),
                "")
    hab = f.get("Descrição da Habilitação Literária", "")
    if "psicolog" not in fold(area) and "psicolog" in fold(f"{hab} {f.get('Caracterização do Posto de Trabalho', '')[:300]}"):
        area = "Psicologia"
    placeholder = {"", "qualquer", "nao aplicavel"}  # categories BEP shows when the career says it all
    category = next((c for c in (f.get("Categoria"), f.get("Carreira")) if fold(c or "").strip() not in placeholder),
                    "Oferta")
    title = f"{category} ({area})" if area else category
    where = []
    for p in places:
        place = ", ".join(x for x in (p.get("Concelho", ""), p.get("Distrito", "")) if x)
        if place and place not in where:
            where.append(place)
    location = f"{' / '.join(where[:3])}, Portugal" if where else "Portugal"
    open_to_all = OPEN_TO_ALL in fold(f.get("Relação Jurídica Exigida", ""))
    mobility = "mobilidade" in fold(f.get("Tipo Oferta", ""))
    lines = [RESTRICTED] if (not open_to_all or mobility) else []
    if f.get("Data Limite"):
        lines.append(f"Data limite de candidatura: {f['Data Limite']}")
    skip = {"Código da Oferta", "Estado", "Data Limite", "Requisitos de Nacionalidade"}
    lines += [f"{k}: {v}" for k, v in f.items() if v and k not in skip]
    if places:
        lines.append("Local de trabalho: " + "; ".join(
            ", ".join(x for x in (p.get("Localidade", ""), p.get("Concelho", ""), p.get("Distrito", "")) if x)
            for p in places))
    return Job(source="bep", ext_id=code, company=re.sub(r"\s+", " ", f.get("Órgão/Serviço", "")).strip() or "BEP",
               title=title, url=url, location=location, remote=False, description="\n".join(lines),
               posted_at=f.get("Data Publicitação") or None, salary=f.get("Remuneração", ""))


def bep(http: Http, profile: dict) -> Iterator[Job]:
    from .. import db

    terms = profile["field_def"].get("bep_searches") or []
    conn = db.connect()
    try:  # offers we've read before come back from the database: no request for them
        known = {r["ext_id"]: r for r in conn.execute(
            "SELECT ext_id, company, title, url, location, description, salary, posted_at FROM jobs "
            "WHERE source = 'bep'").fetchall()}
    finally:
        conn.close()
    seen: set[str] = set()
    for term in terms:
        found = _bep_search(http, term)
        if found is None:
            log.info("  bep: search \"%s\" unavailable, skipping", term)
            continue
        url, soup = found
        state = _form(soup)
        for row in _bep_rows(soup):
            if row["code"] in seen:
                continue
            seen.add(row["code"])
            if row["code"] in known:
                k = known[row["code"]]
                yield Job(source="bep", ext_id=row["code"], company=k["company"], title=k["title"], url=k["url"],
                          location=k["location"], remote=False, description=k["description"] or "",
                          posted_at=k["posted_at"], salary=k["salary"] or "")
                continue
            check_cancel()
            time.sleep(random.uniform(2.0, 4.0))
            # The results' links are form posts; the page they lead to has a plain URL (Oferta_Detalhes.aspx?CodOferta=).
            r = http.post_form(url, {**state, "__EVENTTARGET": row["target"], "__EVENTARGUMENT": ""})
            if r is None or r.status_code != 200 or "CodOferta=" not in str(r.url):
                log.info("  bep: couldn't open %s, skipping it", row["code"])
                continue
            job = bep_offer(r.text, str(r.url))
            if job:
                yield job
