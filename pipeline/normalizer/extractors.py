import re
from dataclasses import dataclass
from datetime import datetime

import dateparser


@dataclass
class NormalizedCandidate:
    title: str
    description: str
    date_start: datetime | None
    date_end: datetime | None
    venue: str
    address: str
    price_min: float | None
    price_max: float | None
    currency: str
    age_limit: str
    tags: list[str]
    images: list[str]
    source_url: str
    parse_confidence: float


AGE_REGEX = re.compile(r"(\d{1,2})\+")

# A run of digits (with thousands spaces), e.g. "1 500" or "2500".
_NUM_RE = re.compile(r"\d[\d\s]*\d|\d")
# Currency markers in RU/EN free text — used to anchor numbers as prices.
_CURRENCY_RE = re.compile(r"(?:рубл\w*|руб\.?|₽|\bр\.|rub|rur)", re.IGNORECASE)
_FREE_RE = re.compile(r"беспл\w*|вход свободн\w*|free", re.IGNORECASE)


def _nums(text: str) -> list[int]:
    out: list[int] = []
    for m in _NUM_RE.finditer(text):
        digits = m.group().replace(" ", "")
        if digits:
            try:
                out.append(int(digits))
            except ValueError:
                continue
    return out


def parse_price_field(text: str) -> tuple[float | None, float | None]:
    """Parse a dedicated price string (e.g. KudaGo ``price``), which is known to
    describe a price, so numbers are trusted directly. Handles RU phrasings:

      "2500 рублей"               -> (2500, 2500)
      "от 1500 рублей"            -> (1500, None)   ("from X")
      "до 700 рублей"             -> (0, 700)       ("up to X")
      "от 0 до 700 рублей"        -> (0, 700)
      "800 рублей за игрока"      -> (800, 800)
      "бесплатно" / "" / "по билету" (no digits) -> (0,0) if free word else (None,None)
    """
    t = (text or "").strip().lower()
    if not t:
        return None, None
    nums = _nums(t)
    if not nums:
        return (0.0, 0.0) if _FREE_RE.search(t) else (None, None)
    has_from = "от " in t or t.startswith("от")
    has_to = "до " in t
    lo, hi = min(nums), max(nums)
    if has_from and has_to:
        return float(lo), float(hi)
    if has_from:
        return float(min(nums)), None
    if has_to:
        return 0.0, float(max(nums))
    if len(nums) == 1:
        return float(nums[0]), float(nums[0])
    return float(lo), float(hi)


def parse_price(text: str) -> tuple[float | None, float | None]:
    """Parse prices from FREE text (descriptions). To avoid picking up phone
    numbers, addresses or years, only numbers sitting just before a currency
    marker (руб./₽/rub) are trusted."""
    if not text:
        return None, None
    found: list[int] = []
    for m in _CURRENCY_RE.finditer(text):
        seg = text[max(0, m.start() - 14) : m.start()]
        near = re.findall(r"\d[\d\s]*\d|\d", seg)
        if near:
            digits = near[-1].replace(" ", "")
            try:
                found.append(int(digits))
            except ValueError:
                continue
    if not found:
        if _FREE_RE.search(text):
            return 0.0, 0.0
        return None, None
    return float(min(found)), float(max(found))


def parse_dates(text: str) -> tuple[datetime | None, datetime | None]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        dt = dateparser.parse(line, languages=["ru", "en"])
        if dt:
            return dt, None
    dt = dateparser.parse(text, languages=["ru", "en"])
    return dt, None


def parse_age(text: str) -> str:
    m = AGE_REGEX.search(text)
    if not m:
        return ""
    return f"{m.group(1)}+"
