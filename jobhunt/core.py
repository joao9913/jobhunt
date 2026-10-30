"""Shared pieces: paths, profile, HTTP client, text helpers, the Job record."""

from __future__ import annotations

import html
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import httpx
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB_PATH = DATA / "jobhunt.db"
PROFILE_PATH = ROOT / "profile.yaml"
COMPANIES_PATH = ROOT / "companies.yaml"

log = logging.getLogger("jobhunt")

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


@dataclass
class Job:
    source: str
    ext_id: str
    company: str
    title: str
    url: str
    location: str = ""
    remote: bool | None = None
    description: str = ""
    posted_at: str | None = None  # ISO date
    tags: list[str] = field(default_factory=list)
    salary: str = ""
    # Optional company facts from the source: size, startup, blurb, stage.
    company_meta: dict | None = None


def load_profile() -> dict:
    return yaml.safe_load(PROFILE_PATH.read_text())


def load_seed_companies() -> list[dict]:
    return yaml.safe_load(COMPANIES_PATH.read_text()) or []


@cache
def cv_text() -> str:
    path = Path(load_profile()["cv_file"]).expanduser()
    if not path.exists():
        return ""
    raw = path.read_text()
    return html_to_text(raw) if path.suffix in {".html", ".htm"} else raw


# ---------- text ----------

_LEGAL = re.compile(
    r"\b(gmbh|ltd|limited|inc|llc|s\.?a\.?|lda|unipessoal|se|ag|plc|b\.?v\.?|n\.?v\.?|s\.?l\.?|"
    r"sas|srl|spa|co|corp|corporation|group|holding|portugal|technology|technologies)\b\.?"
)


def company_key(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = _LEGAL.sub(" ", s)
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s or re.sub(r"[^a-z0-9]+", "", name.lower())


def title_key(title: str) -> str:
    s = title.lower()
    s = re.sub(r"\(.*?\)|\[.*?\]", " ", s)
    s = re.sub(r"\b(m/w/d|f/m/d|m/f/d|w/m/d|h/m|m/f|f/m)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def html_to_text(raw: str) -> str:
    if not raw:
        return ""
    if "&lt;" in raw and "<" not in raw:  # Greenhouse double-escapes content
        raw = html.unescape(raw)
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["style", "script", "noscript"]):
        tag.decompose()
    for br in soup.find_all(["br", "p", "li", "div", "h1", "h2", "h3", "h4", "tr"]):
        br.insert_before("\n")
    text = soup.get_text(" ")
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def has_term(text: str, term: str) -> bool:
    """Whole-word-ish match that works for terms like 'ci/cd', 'u.s.' or 'c#'."""
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None


# ---------- countries ----------

# Country -> extra names and well-known cities/regions that appear without the country ("Berlin", "London").
_COUNTRIES: dict[str, list[str]] = {
    "Portugal": ["lisbon", "lisboa", "porto", "braga", "coimbra", "aveiro", "leiria", "oeiras", "almada",
                 "amadora", "cascais", "sintra", "vila nova de gaia", "matosinhos", "faro", "funchal"],
    "Spain": ["espana", "madrid", "barcelona", "valencia", "seville", "sevilla", "malaga", "bilbao", "granada",
              "catalonia", "andalusia"],
    "France": ["paris", "lyon", "toulouse", "bordeaux", "lille", "nantes", "marseille", "rennes", "grenoble",
               "nice", "ile-de-france"],
    "Germany": ["deutschland", "berlin", "munich", "munchen", "hamburg", "frankfurt", "cologne", "koln",
                "stuttgart", "dusseldorf", "nurnberg", "nuremberg", "bavaria", "hesse"],
    "United Kingdom": ["uk", "england", "scotland", "wales", "great britain", "london", "manchester",
                       "edinburgh", "bristol", "cambridge", "oxford", "birmingham", "belfast", "cardiff"],
    "Ireland": ["dublin", "cork", "galway", "limerick"],
    "Netherlands": ["the netherlands", "holland", "amsterdam", "rotterdam", "utrecht", "the hague", "eindhoven",
                    "delft", "randstad"],
    "Belgium": ["brussels", "antwerp", "ghent", "leuven"],
    "Luxembourg": [],
    "Switzerland": ["zurich", "geneva", "basel", "lausanne", "bern", "zug"],
    "Austria": ["vienna", "wien", "linz", "graz", "salzburg"],
    "Italy": ["italia", "milan", "milano", "rome", "roma", "turin", "torino", "bologna", "florence", "naples"],
    "Poland": ["warsaw", "warszawa", "krakow", "cracow", "wroclaw", "gdansk", "poznan", "lodz", "katowice"],
    "Czechia": ["czech republic", "prague", "brno"],
    "Slovakia": ["bratislava"],
    "Hungary": ["budapest"],
    "Romania": ["bucharest", "cluj", "iasi", "timisoara"],
    "Bulgaria": ["sofia", "plovdiv"],
    "Greece": ["athens", "thessaloniki"],
    "Croatia": ["zagreb", "rijeka", "split"],
    "Serbia": ["belgrade", "novi sad"],
    "North Macedonia": [],
    "Slovenia": ["ljubljana"],
    "Denmark": ["copenhagen", "aarhus"],
    "Sweden": ["stockholm", "gothenburg", "malmo", "vasteras"],
    "Norway": ["oslo"],
    "Finland": ["helsinki", "espoo", "tampere", "turku"],
    "Iceland": [],
    "Estonia": ["tallinn"],
    "Latvia": ["riga"],
    "Lithuania": ["vilnius", "kaunas"],
    "Ukraine": ["kyiv", "kiev", "lviv"],
    "Armenia": ["yerevan"],
    "Georgia": ["tbilisi"],
    "Turkey": ["turkiye", "istanbul"],
    "Cyprus": ["limassol", "nicosia"],
    "Malta": [],
    "Israel": ["tel aviv"],
    "United Arab Emirates": ["uae", "dubai", "abu dhabi"],
    "Saudi Arabia": [],
    "Morocco": ["casablanca"],
    "Tunisia": ["tunis"],
    "Egypt": ["cairo"],
    "Nigeria": ["lagos"],
    "Kenya": ["nairobi"],
    "South Africa": ["cape town", "johannesburg"],
    "Senegal": ["dakar"],
    "United States": ["usa", "us", "u.s.", "united states of america", "new york", "san francisco", "seattle",
                      "boston", "chicago", "austin", "denver", "houston", "palo alto", "san jose",
                      "los angeles", "orlando", "atlanta", "miami", "washington d.c.", "california", "texas"],
    "Canada": ["toronto", "vancouver", "montreal", "ottawa", "calgary", "mississauga", "waterloo"],
    "Mexico": ["mexico city"],
    "Brazil": ["brasil", "sao paulo"],
    "Argentina": ["buenos aires"],
    "Colombia": ["bogota", "medellin"],
    "Chile": [],
    "India": ["bengaluru", "bangalore", "hyderabad", "pune", "mumbai", "delhi", "chennai"],
    "Singapore": [],
    "Japan": ["tokyo"],
    "China": ["beijing", "shanghai"],
    "Taiwan": ["taipei"],
    "Australia": ["sydney", "melbourne"],
    "New Zealand": ["auckland"],
}
# Two-letter codes only count as a whole segment ("Lisbon, PT", "Remote (FR; CH)"). Codes that are also
# US state abbreviations (CA, CO, GA, IN, MD, ...) are left out on purpose.
_CODES = {"PT": "Portugal", "ES": "Spain", "FR": "France", "DE": "Germany", "GB": "United Kingdom",
          "IE": "Ireland", "NL": "Netherlands", "BE": "Belgium", "CH": "Switzerland", "AT": "Austria",
          "IT": "Italy", "PL": "Poland", "RO": "Romania", "BG": "Bulgaria", "SE": "Sweden", "DK": "Denmark",
          "FI": "Finland", "NO": "Norway", "MX": "Mexico", "BR": "Brazil", "CL": "Chile"}
_ANYWHERE = ("remote", "remoto", "worldwide", "anywhere", "global", "home based", "europe", "european", "emea", "eu")
PORTUGAL_PLACES = _COUNTRIES["Portugal"]
REMOTE_NO_COUNTRY = "Remote (no country)"
UNKNOWN_COUNTRY = "Unknown"


def ascii_lower(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


_COUNTRY_TERMS = [(ascii_lower(term), country) for country, extra in _COUNTRIES.items()
                  for term in [country, *extra]]


def countries(location: str | None, remote: bool | int | None = None) -> list[str]:
    """Countries a free-text location mentions, in order. Falls back to a remote or unknown bucket."""
    text = ascii_lower(location or "")
    found: list[str] = []
    for seg in re.split(r"[,;/()|]", location or ""):
        if (c := _CODES.get(seg.strip())) and c not in found:
            found.append(c)
    hits = sorted((m.start(), c) for term, c in _COUNTRY_TERMS
                  for m in re.finditer(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text))
    for _, c in hits:
        if c not in found:
            found.append(c)
    if found:
        return found
    if remote or any(has_term(text, w) for w in _ANYWHERE):
        return [REMOTE_NO_COUNTRY]
    return [UNKNOWN_COUNTRY]


def ts_to_iso(ts: float | int | None) -> str | None:
    if not ts:
        return None
    if ts > 10_000_000_000:  # milliseconds
        ts = ts / 1000
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def iso_date(s: str | None) -> str | None:
    return s[:10] if s else None


# ---------- HTTP ----------


class Http:
    def __init__(self) -> None:
        self.client = httpx.Client(
            headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
            timeout=httpx.Timeout(25.0, connect=10.0),
            follow_redirects=True,
        )

    def get(self, url: str, *, retries: int = 2, **kw) -> httpx.Response | None:
        for attempt in range(retries + 1):
            try:
                r = self.client.get(url, **kw)
            except httpx.HTTPError as e:
                log.debug("GET %s failed: %s", url, e)
                if attempt == retries:
                    return None
                time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(3 * (attempt + 1))
                continue
            return r
        return None

    def json(self, url: str, **kw):
        r = self.get(url, **kw)
        if r is None or r.status_code != 200:
            return None
        try:
            return r.json()
        except ValueError:
            return None

    def post_json(self, url: str, payload: dict):
        try:
            r = self.client.post(url, json=payload)
        except httpx.HTTPError:
            return None
        if r.status_code != 200:
            return None
        try:
            return r.json()
        except ValueError:
            return None
