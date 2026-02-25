import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import dateparser
import httpx

from core.config.settings import get_settings


@dataclass
class ExtractedEvent:
    title: str
    description: str
    date_start: str
    date_end: str
    venue: str
    address: str
    price_text: str
    age_limit: str
    tags: list[str]
    confidence: float


class LLMExtractionService:
    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = settings.llm_api_base_url.rstrip("/")
        self.timeout_seconds = settings.llm_timeout_seconds

    @staticmethod
    def _parse_dt(value: str) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return dateparser.parse(value, languages=["ru", "en"])

    async def extract_event_with_reason(self, text: str, city_hint: str = "Moscow") -> tuple[ExtractedEvent | None, str]:
        if not text or len(text.strip()) < 30:
            return None, "too_short"

        prompt = (
            "Extract a structured event from Telegram post text. "
            "Return ONLY JSON without markdown. "
            "If this is not an event announcement or critical fields are missing, return "
            '{"is_event":false}. '
            "Critical fields are: title, date_start, and at least one of venue/address. "
            "JSON format: "
            '{"is_event":true,"title":"","description":"","date_start":"","date_end":"","venue":"",'
            '"address":"","price_text":"","age_limit":"","tags":[],"confidence":0.0}. '
            "date_start/date_end must be ISO-8601. city_hint="
            f"{city_hint}."
        )
        payload = {
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": text[:12000]},
            ],
            "stream": False,
            "temperature": 0.1,
            "max_tokens": 500,
        }

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

        raw = data.get("response") or "{}"
        try:
            parsed: dict[str, Any] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None, "invalid_json"

        if not parsed.get("is_event"):
            return None, "not_event"

        title = str(parsed.get("title") or "").strip()
        description = str(parsed.get("description") or "").strip() or text[:12000]
        date_start = str(parsed.get("date_start") or "").strip()
        date_end = str(parsed.get("date_end") or "").strip()
        venue = str(parsed.get("venue") or "").strip()
        address = str(parsed.get("address") or "").strip()
        price_text = str(parsed.get("price_text") or "").strip()
        age_limit = str(parsed.get("age_limit") or "").strip()
        tags = [str(tag).strip().lower() for tag in (parsed.get("tags") or []) if str(tag).strip()]
        confidence = float(parsed.get("confidence") or 0.0)

        if not title:
            return None, "missing_title"
        if self._parse_dt(date_start) is None:
            return None, "missing_or_invalid_date"
        if not (venue or address):
            return None, "missing_venue_address"
        if confidence < 0.55:
            return None, "low_confidence"

        return (
            ExtractedEvent(
                title=title,
                description=description,
                date_start=date_start,
                date_end=date_end,
                venue=venue,
                address=address,
                price_text=price_text,
                age_limit=age_limit,
                tags=list(dict.fromkeys(tags)),
                confidence=confidence,
            ),
            "ok",
        )

    async def extract_event(self, text: str, city_hint: str = "Moscow") -> ExtractedEvent | None:
        event, _ = await self.extract_event_with_reason(text, city_hint=city_hint)
        return event
