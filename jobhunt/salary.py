"""The salary a posting offers, from the board's own field or from its description.

Most boards (LinkedIn, Greenhouse, Ashby...) have no salary field, but many descriptions state it:
"Salary range: €35,000 – €53,000 gross/year", "48,000 - 60,000 EUR", "€ 3.600 to € 5.000 monthly".
Funding rounds, revenue and equipment budgets look alike, so a bare amount only counts next to a
word like "salary", and amounts after "raised", "Series A", "revenue"... are skipped.
"""

from __future__ import annotations

import re

_CUR = r"(?:€|£|\$|US\$|EUR|USD|GBP|CHF|PLN|SEK|NOK|DKK)"
_NUM = r"\d{1,3}(?:[.,\s]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d+)?"
_AMOUNT = rf"(?P<c#a>{_CUR})?\s?(?P<v#>{_NUM})\s?(?P<k#>k\b|mil\b)?\s?(?P<c#b>{_CUR}|euros?\b)?"
_RANGE = re.compile(
    _AMOUNT.replace("#", "1") + r"[\s‑-]*(?:-|–|—|‑|to|and|a|até|e)[\s‑-]*" + _AMOUNT.replace("#", "2"), re.I)
_SINGLE = re.compile(_AMOUNT.replace("#", "1"), re.I)

_SALARY_WORDS = re.compile(
    r"salary|salário|salario|remunera|compensation|pay range|base pay|gross|bruto|ordenado|vencimento|"
    r"\bpay\b|\bote\b|\brate\b|tarifa", re.I)
_NOT_SALARY = re.compile(
    r"raised|raise|series [a-e]|funding|funded|valuation|revenue|turnover|assets|invest|budget|allowance|"
    r"stipend|bonus of|grant|arr\b|\bin sales|backed|worth", re.I)
_PERIODS = [("hour", re.compile(r"hour|/h\b|/hr|per hr|hora", re.I)),
            ("day", re.compile(r"\bday\b|/day|daily|\bdia\b", re.I)),
            ("month", re.compile(r"month|/mo\b|mensal|\bmês|\bmes\b|monthly", re.I)),
            ("year", re.compile(r"year|annual|annum|/yr|\bp\.?a\b|\bano\b|anual", re.I))]
_SYMBOL = {"eur": "€", "euro": "€", "euros": "€", "usd": "$", "us$": "$", "gbp": "£"}
# Plausible pay per period in euros, dollars or pounds; other currencies scale by _SCALE.
_RANGES = {"hour": (8, 500), "day": (80, 3000), "month": (500, 30_000), "year": (10_000, 600_000)}
_SCALE = {"SEK": 10, "NOK": 10, "DKK": 7, "PLN": 4}


def _value(m: re.Match, n: int) -> float | None:
    raw = m.group(f"v{n}")
    if re.fullmatch(r"\d{1,3}(?:[.,\s]\d{3})+", raw):  # 35,000 / 35.000 / 35 000
        v = float(re.sub(r"[.,\s]", "", raw))
    elif re.fullmatch(r"\d{1,3}(?:[.,\s]\d{3})+[.,]\d{1,2}", raw):  # 35,000.00
        v = float(re.sub(r"[.,\s]", "", raw[:-3]))
    else:
        v = float(raw.replace(",", "."))
    if m.group(f"k{n}"):
        v *= 1000
    return v


def _currency(m: re.Match, n: int) -> str:
    c = m.group(f"c{n}a") or m.group(f"c{n}b") or ""
    return _SYMBOL.get(c.lower(), c)


def _period(before: str, after: str, lo: float, hi: float, cur: str) -> str | None:
    """The pay period: the first one named next to the amount that its size fits, else a guess from the size."""
    scale = _SCALE.get(cur, 1)
    fits = lambda p: _RANGES[p][0] * scale <= lo <= hi <= _RANGES[p][1] * scale
    named = sorted((m.start(), name) for name, rx in _PERIODS if (m := rx.search(after)))
    named += [(99, name) for name, rx in _PERIODS if rx.search(before)]
    for _, name in named:
        if fits(name):
            return name
    if named:
        return None
    return next((p for p in ("month", "year") if fits(p)), None)


def _fmt(v: float) -> str:
    return f"{v / 1000:g}k" if v >= 10_000 else f"{v:,.0f}"


def _candidate(text: str, m: re.Match, lo: float, hi: float, cur: str) -> str | None:
    before = text[max(0, m.start() - 60):m.start()]
    if _NOT_SALARY.search(before) or re.match(r"\s?(?:m\b|mn\b|million|milh|b\b|bn\b|billion)", text[m.end():], re.I):
        return None
    period = _period(text[max(0, m.start() - 40):m.start()], text[m.end():m.end() + 40], lo, hi, cur)
    if not period or hi > lo * 10:
        return None
    cur = cur if len(cur) == 1 else cur + " "
    amount = f"{cur}{_fmt(lo)}" + (f"–{_fmt(hi)}" if hi != lo else "")
    if hi == lo and (q := re.search(r"(up to|under|max(?:imum)?|from|starting at|min(?:imum)?|at least|até|a partir de)\W*(?:\w+\W+){0,6}$",
                                    text[max(0, m.start() - 50):m.start()], re.I)):
        amount = f"{q.group(1).lower()} {amount}"
    return f"{amount} / {period}"


def from_text(text: str) -> str | None:
    """The pay range stated in a description, like "€35k–53k / year", or None."""
    if not text:
        return None
    for m in _RANGE.finditer(text):
        cur = _currency(m, 1) or _currency(m, 2)
        if not cur:
            continue
        lo, hi = _value(m, 1), _value(m, 2)
        if m.group("k2") and not m.group("k1") and lo < 1000:  # "€40-50k"
            lo *= 1000
        found = _candidate(text, m, lo, hi, cur)
        if found:
            return found
    for m in _SINGLE.finditer(text):
        cur = _currency(m, 1)
        if not cur or not _SALARY_WORDS.search(text[max(0, m.start() - 80):m.start()]):
            continue
        v = _value(m, 1)
        found = _candidate(text, m, v, v, cur)
        if found:
            return found
    return None


def salary(field: str | None, description: str | None) -> tuple[str | None, bool]:
    """(salary, came from the description). The board's own field wins when it has one."""
    if field and field.strip() and re.search(r"\d", field):
        return field.strip(), False
    found = from_text(description or "")
    return found, bool(found)
