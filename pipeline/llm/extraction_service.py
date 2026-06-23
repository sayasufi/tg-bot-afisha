import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import dateparser
import httpx

# Moscow is a fixed UTC+3 (no DST since 2014). Telegram posts state local MSK time with no offset.
_MSK = timezone(timedelta(hours=3))

from core.config.settings import get_settings
from core.llm_limiter import llm_slot
from pipeline.geocoding.providers.yandex_maps import YandexMapsScraper
from pipeline.llm.json_utils import parse_llm_json


@dataclass
class ExtractedEvent:
    title: str
    description: str
    date_start: str
    date_end: str
    venue: str
    address: str
    address_candidates: list[str]
    price_text: str
    age_limit: str
    tags: list[str]
    confidence: float


class LLMExtractionService:
    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = settings.llm_api_base_url.rstrip("/")
        self.timeout_seconds = settings.llm_timeout_seconds
        self.yandex_maps = YandexMapsScraper()

    @staticmethod
    def _parse_dt(value: str) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return dateparser.parse(value, languages=["ru", "en"])

    @staticmethod
    def _to_msk_iso(value: str) -> str:
        """Anchor a naive LLM date to MSK. A post says «23.06 21:00» (Moscow local); the LLM returns a
        naive «2026-06-23T21:00:00», which the timezone-aware DB column then mis-reads as 21:00 UTC =
        00:00 next day (so a 23 Jun 21:00 event surfaced as «24 июня»). Tag naive datetimes as UTC+3 so
        the stored instant is the real Moscow time. Offset-aware values pass through untouched."""
        if not value:
            return value
        dt = LLMExtractionService._parse_dt(value)
        if dt is None:
            return value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_MSK)
        return dt.isoformat()

    async def extract_events_with_reason(
        self, text: str, city_hint: str = "Moscow", venue_hint: str = "", post_date: str = ""
    ) -> tuple[list[ExtractedEvent], str]:
        """Extract ALL events from a post. A schedule post («21.06 — Фильм А, 22.06 — Фильм Б») yields one
        event per dated line; a normal post yields one; a non-event yields []."""
        if not text or len(text.strip()) < 30:
            return [], "too_short"

        prompt = (
            "Извлеки события из текста Telegram-поста. Верни ТОЛЬКО JSON без markdown. "
            'Формат: {"is_event":true,"events":[{...},{...}]}. '
            "Если пост — РАСПИСАНИЕ/афиша из НЕСКОЛЬКИХ событий на РАЗНЫЕ даты (напр. «21.06 — Фильм А, "
            "22.06 — Фильм Б»), верни в events ОТДЕЛЬНЫЙ объект на КАЖДОЕ событие, с ЕГО конкретной датой "
            "из его строки — НЕ общий диапазон шапки. Если событие одно — events из одного объекта. "
            'Если это не анонс события или нет ключевых полей — верни {"is_event":false}. '
            "Ключевые поля каждого: title, date_start, и хотя бы одно из venue/address. "
            'Каждый объект events: {"title":"","description":"","date_start":"","date_end":"","venue":"",'
            '"address":"","price_text":"","age_limit":"","tags":[],"confidence":0.0}. '
            "date_start/date_end в ISO-8601. "
            "ВСЕ числа пиши ЦИФРАМИ, НЕ словами: дом/строение/корпус в address ("
            "«Петровка 21, стр. 1», а НЕ «двадцать один»), возраст в age_limit («18+», а НЕ «восемнадцать»). "
            "title — реальное название события из текста (НЕ «Новое мероприятие»/«Концерт»); "
            "если в посте только афиша-картинка без названия в тексте — верни is_event:false. "
            "city_hint="
            f"{city_hint}."
        )
        if post_date:
            prompt += (
                f" Пост опубликован {post_date}. ЕСЛИ в тексте есть ЯВНАЯ дата числом («21.06», «21 июня») — "
                "бери ИМЕННО ЕЁ дословно, НЕ пересчитывай день недели сам. Относительные даты («сегодня», "
                "«завтра», «в это воскресенье») считай ОТ ДАТЫ ПУБЛИКАЦИИ поста, а НЕ от текущего дня. Если "
                "КОНКРЕТНОЙ даты события в тексте НЕТ — НЕ придумывай, верни is_event:false. "
                "ВРЕМЯ (часы) в date_start ставь ТОЛЬКО если в посте есть конкретный ЧАС начала («19:00», «в 7 "
                "вечера»). Если часа нет («по вечерам», «вечером», «днём») — верни дату БЕЗ времени, час НЕ выдумывай."
            )
        if venue_hint:
            prompt += (
                f" Этот канал — площадка: {venue_hint}. Если событие проходит на ЭТОЙ площадке (пост не "
                "называет другое место) — поставь её в venue/address. Если в посте указано ДРУГОЕ место — "
                "используй его. Привязка к площадке повышает уверенность, что пост — анонс события."
            )
        payload = {
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": text[:12000]},
            ],
            "stream": False,
            "temperature": 0.1,
            "max_tokens": 1200,  # room for a multi-event schedule array
        }

        try:
            async with llm_slot():  # one of the service-wide LLM concurrency slots
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.post(f"{self.base_url}/api/chat", json=payload)
                    response.raise_for_status()
                    data = response.json()
        except (httpx.HTTPError, ValueError):
            # Network/timeout/5xx/non-JSON — skip this one raw, never abort the batch.
            return [], "llm_error"

        raw = data.get("response") or "{}"
        try:
            parsed: dict[str, Any] = parse_llm_json(raw)
        except (json.JSONDecodeError, TypeError):
            return [], "invalid_json"
        if not isinstance(parsed, dict):
            return [], "invalid_json"

        raw_events = parsed.get("events")
        if not isinstance(raw_events, list):
            # Tolerate the old single-object shape ({"is_event":true,"title":…}).
            raw_events = [parsed] if parsed.get("is_event") else []
        if not raw_events:
            return [], "not_event"

        out: list[ExtractedEvent] = []
        last_reason = "not_event"
        for ev in raw_events[:25]:  # cap a runaway schedule
            if not isinstance(ev, dict):
                continue
            built, reason = await self._build_one(ev, text, city_hint)
            if built is not None:
                out.append(built)
            else:
                last_reason = reason
        return (out, "ok") if out else ([], last_reason)

    async def _build_one(self, parsed: dict, text: str, city_hint: str) -> tuple[ExtractedEvent | None, str]:
        """Validate one LLM event object into an ExtractedEvent (or a skip reason)."""
        title = str(parsed.get("title") or "").strip()
        description = str(parsed.get("description") or "").strip() or text[:12000]
        date_start = self._to_msk_iso(str(parsed.get("date_start") or "").strip())
        date_end = self._to_msk_iso(str(parsed.get("date_end") or "").strip())
        venue = str(parsed.get("venue") or "").strip()
        address = str(parsed.get("address") or "").strip()
        address_candidates: list[str] = []
        if not address and venue:
            address, address_candidates = await self._resolve_address_from_yandex_maps(
                venue=venue,
                city_hint=city_hint,
                source_text=text,
            )
        price_text = str(parsed.get("price_text") or "").strip()
        age_limit = str(parsed.get("age_limit") or "").strip()
        tags = [str(tag).strip().lower() for tag in (parsed.get("tags") or []) if str(tag).strip()]
        try:
            confidence = float(parsed.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0

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
                address_candidates=address_candidates,
                price_text=price_text,
                age_limit=age_limit,
                tags=list(dict.fromkeys(tags)),
                confidence=confidence,
            ),
            "ok",
        )

    async def extract_event_with_reason(
        self, text: str, city_hint: str = "Moscow", venue_hint: str = "", post_date: str = ""
    ) -> tuple[ExtractedEvent | None, str]:
        """Back-compat single-event wrapper — returns the first extracted event."""
        events, reason = await self.extract_events_with_reason(
            text, city_hint=city_hint, venue_hint=venue_hint, post_date=post_date
        )
        return (events[0], "ok") if events else (None, reason)

    async def _resolve_address_from_yandex_maps(
        self,
        venue: str,
        city_hint: str,
        source_text: str,
    ) -> tuple[str, list[str]]:
        try:
            candidates = await self.yandex_maps.find_addresses_by_place(venue, city_hint=city_hint, limit=5)
        except Exception:
            return "", []
        if not candidates:
            return "", []
        best = self._pick_best_address(candidates, source_text=source_text)
        return best, candidates

    @staticmethod
    def _pick_best_address(candidates: list[str], source_text: str) -> str:
        if not candidates:
            return ""
        lowered_text = (source_text or "").casefold()
        if not lowered_text:
            return candidates[0]

        def score(addr: str) -> int:
            words = [word for word in re.split(r"[^\w]+", addr.casefold()) if len(word) >= 4]
            return sum(1 for word in words if word in lowered_text)

        ranked = sorted(candidates, key=lambda addr: score(addr), reverse=True)
        return ranked[0]

    async def extract_event(self, text: str, city_hint: str = "Moscow", venue_hint: str = "", post_date: str = "") -> ExtractedEvent | None:
        event, _ = await self.extract_event_with_reason(text, city_hint=city_hint, venue_hint=venue_hint, post_date=post_date)
        return event
