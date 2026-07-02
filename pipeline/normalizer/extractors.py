import re
from datetime import datetime

import dateparser

from core.contracts import NormalizedCandidate  # noqa: F401 — re-export для обратной совместимости (контракт в core)


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
    # A17: скидочные проценты («скидка до 20%») — не цена и не граница. Убираем ДО разбора, иначе
    # число 20 попадало в nums и «до» делало price_min=0 (платное событие выглядело частично бесплатным).
    t = re.sub(r"\d+\s*%", "", t)
    nums = _nums(t)
    if not nums:
        return (0.0, 0.0) if _FREE_RE.search(t) else (None, None)
    # «от»/«до» как границы цены — только когда за маркером идёт ЧИСЛО (а не «скидка до …%», где числа уже нет).
    has_from = bool(re.search(r"\bот\s*\d", t))
    has_to = bool(re.search(r"\bдо\s*\d", t))
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


# A17: a bare "19:00"/"5 мая" is Moscow local wall-clock, not UTC. Without a timezone the parsed
# datetime is naive → downstream treats it as UTC → the event time shifts +3h. Interpret naive results
# as Europe/Moscow and return tz-aware, mirroring the already-tz-aware parse in rules.py.
_DP_SETTINGS = {"TIMEZONE": "Europe/Moscow", "RETURN_AS_TIMEZONE_AWARE": True}


def parse_dates(text: str) -> tuple[datetime | None, datetime | None]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        dt = dateparser.parse(line, languages=["ru", "en"], settings=_DP_SETTINGS)
        if dt:
            return dt, None
    dt = dateparser.parse(text, languages=["ru", "en"], settings=_DP_SETTINGS)
    return dt, None


def parse_age(text: str) -> str:
    m = AGE_REGEX.search(text)
    if not m:
        return ""
    return f"{m.group(1)}+"
