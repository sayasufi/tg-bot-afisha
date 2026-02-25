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


PRICE_REGEX = re.compile(r"(\d+[\s\d]*)\s?(?:rub|rur|RUB)", re.IGNORECASE)
AGE_REGEX = re.compile(r"(\d{1,2})\+")


def parse_price(text: str) -> tuple[float | None, float | None]:
    hits = PRICE_REGEX.findall(text)
    if not hits:
        return None, None
    nums = [float(h.replace(" ", "")) for h in hits]
    return min(nums), max(nums)


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
