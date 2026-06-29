"""Общие контракты-данные между слоями (dataclass'ы без логики и IO).

Foundation-уровень: живут в core, чтобы и нормализатор (производит), и core.db.repositories (потребляет)
ссылались на ОДИН контракт, не нарушая слои (раньше core тянул pipeline ради этого типа)."""
from dataclasses import dataclass
from datetime import datetime


@dataclass
class NormalizedCandidate:
    """Нормализованное событие-кандидат на выходе нормализатора, на входе ingestion-репозитория."""
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
