import asyncio
import html as html_lib
import json
import re
from datetime import datetime, timedelta, timezone

from curl_cffi.requests import AsyncSession

from connectors.base import RawRecord
from core.config.settings import get_settings

# Afisha's edge fingerprints the TLS handshake (JA3/JA4) and 403s plain Python
# clients (httpx/requests use OpenSSL). curl_cffi bundles BoringSSL and impersonates
# a real Chrome handshake, which the edge accepts.
_IMPERSONATE = "chrome"

# Moscow is a fixed UTC+3 the whole year (no DST since 2014) — use a plain offset
# so we don't depend on the tzdata package being present in every environment.
_MSK = timezone(timedelta(hours=3))
_LOOKAHEAD_DAYS = 30
# Open-ended sentinel for `permanent` events: an end far enough out that the UI's
# ">now+5y" rule renders it as "постоянно" (mirrors KudaGo's open-ended handling).
_FAR_FUTURE_TS = int(datetime(2099, 1, 1, tzinfo=timezone.utc).timestamp())

# Yandex Afisha drives its whole site off one GraphQL endpoint. `actualEvents`
# is the city-wide feed (paginated, date-filtered). We request only the fields the
# pipeline needs; descriptions live on `Event` (not `EventPreview`) and are pulled
# separately in a batched follow-up so the bulk list stays cheap.
_LIST_QUERY = (
    "query Events($paging:PagingInput,$dates:DaysIntervalInput){"
    "actualEvents(paging:$paging,dates:$dates){"
    "paging{limit offset total} "
    "items{"
    "event{id url title argument contentRating "
    "type{code name} "
    "tags(codeNotIn:[\"other\"],status:approved){code name} "
    "image{cover:image(size:s380x220_crop){url} orig:image(size:origin){url}} "
    "tickets{price{currency min max}}} "
    "scheduleInfo{dates dateStarted dateEnd permanent "
    "regularity{singleShowtime} "
    "onlyPlace{id title address coordinates{latitude longitude} metro{name}} "
    "oneOfPlaces{id title address coordinates{latitude longitude} metro{name}}}"
    "}}}"
)


class YandexAfishaConnector:
    """Pulls events from Yandex Afisha's public GraphQL API.

    Shape mirrors :class:`KudaGoConnector`: ``async fetch(cursor) -> (records, next_cursor)``
    where the cursor is a paging offset. The produced payloads deliberately use the
    same KudaGo-style keys (``dates`` as unix rows, ``place.coords`` as ``{lat,lon}``,
    ``price`` as a RU text field, ``categories``/``tags`` as hint lists) so they flow
    through the existing RuleBasedNormalizer -> enrich -> dedup pipeline unchanged.

    The only "auth" the edge needs is an EMPTY ``x-csrf-token`` header plus a
    ``yandexuid`` cookie and a *named* GraphQL operation — there is no login/captcha.
    """

    source_name = "yandex_afisha"
    _DATES_CAP = 8
    _DESC_CHUNK = 25  # event ids per batched description request

    def __init__(self, city: str = "moscow", page_size: int = 100, with_descriptions: bool = True) -> None:
        self.settings = get_settings()
        self.city = city
        self.page_size = page_size
        self.with_descriptions = with_descriptions

    # --- HTTP plumbing -----------------------------------------------------

    @property
    def _endpoint(self) -> str:
        return f"{self.settings.yandex_afisha_base_url}?city={self.city}&version=560.0.0"

    def _headers(self) -> dict[str, str]:
        # curl_cffi's impersonation supplies the browser-consistent UA / sec-ch-ua /
        # accept headers; we only add the request-specific ones the edge checks.
        return {
            "content-type": "application/json",
            # Empty CSRF header is required: the edge returns 405 without it.
            "x-csrf-token": "",
            "x-force-cors-preflight": "1",
            "origin": "https://afisha.yandex.ru",
            "referer": f"https://afisha.yandex.ru/{self.city}",
            "accept-language": "ru-RU,ru;q=0.9",
            # Any yandexuid is accepted; it only scopes anonymous personalization.
            "cookie": "yandexuid=4441728991700000000",
        }

    async def _post(self, session: AsyncSession, body: dict) -> dict:
        response = await session.post(
            self._endpoint,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(),
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    async def _fetch_page(self, session: AsyncSession, offset: int, today) -> tuple[list[RawRecord], int]:
        """One page of `actualEvents` -> (records, total). Raises on GraphQL errors so
        the Celery task fails loudly instead of silently treating an API error (rate
        limit, outage) as 'no events'."""
        body = {
            "operationName": "Events",
            "variables": {
                "paging": {"limit": self.page_size, "offset": offset},
                "dates": {"date": today.isoformat(), "period": _LOOKAHEAD_DAYS},
            },
            "query": _LIST_QUERY,
        }
        data = await self._post(session, body)
        errors = data.get("errors")
        if errors:
            messages = "; ".join(str(e.get("message", e)) for e in errors if isinstance(e, dict))
            raise RuntimeError(f"Yandex Afisha GraphQL error: {messages or errors}")
        block = (data.get("data") or {}).get("actualEvents")
        if not isinstance(block, dict):
            block = {}
        total = int((block.get("paging") or {}).get("total") or 0)
        items = block.get("items") if isinstance(block.get("items"), list) else []
        records = self._build_records(items, today)
        if self.with_descriptions and records:
            await self._augment_descriptions(session, records)
        return records, total

    async def fetch(self, cursor: str | None = None) -> tuple[list[RawRecord], str | None]:
        offset = int(cursor) if cursor and str(cursor).isdigit() else 0
        today = datetime.now(_MSK).date()
        async with AsyncSession(impersonate=_IMPERSONATE) as session:
            records, total = await self._fetch_page(session, offset, today)

        # Cursor is the next offset. At the end it stays equal to the current offset
        # (stable) so the full-scan task detects completion; the incremental task
        # wraps it back to "0" itself.
        next_off = offset + self.page_size
        next_cursor = str(next_off) if 0 < total > next_off else str(offset)
        return records, next_cursor

    async def scan(self, max_pages: int = 40) -> tuple[list[RawRecord], int, str]:
        """Full in-window sweep over every offset, reusing ONE session (one TLS
        handshake) across all pages. Returns (records, pages_scanned, stop_reason);
        de-duplicates by external_id in case the feed shifts mid-scan."""
        today = datetime.now(_MSK).date()
        all_records: list[RawRecord] = []
        seen: set[str] = set()
        pages = 0
        stop_reason = "max_pages"
        async with AsyncSession(impersonate=_IMPERSONATE) as session:
            offset = 0
            while pages < max_pages:
                records, total = await self._fetch_page(session, offset, today)
                pages += 1
                for rec in records:
                    if rec.external_id not in seen:
                        seen.add(rec.external_id)
                        all_records.append(rec)
                if not records:
                    stop_reason = "empty_page"
                    break
                offset += self.page_size
                if offset >= total:
                    stop_reason = "exhausted"
                    break
                stop_reason = "completed_iteration"
        return all_records, pages, stop_reason

    # --- Record building ---------------------------------------------------

    def _build_records(self, items: list, today) -> list[RawRecord]:
        records: list[RawRecord] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            event = item.get("event") or {}
            schedule = item.get("scheduleInfo") or {}
            event_id = event.get("id")
            if not event_id:
                continue

            base = {
                "id": event_id,
                "title": event.get("title"),
                "description": self._strip_html(event.get("argument")),  # upgraded to full text below
                "dates": self._build_dates(schedule, today),
                "site_url": self._abs_url(event.get("url")),
                "images": self._images(event.get("image")),
                "categories": self._categories(event.get("type")),
                "tags": self._tags(event.get("tags")),
                "age_restriction": event.get("contentRating"),
            }
            price_text, is_free = self._price(event.get("tickets"))
            base["price"] = price_text
            base["is_free"] = is_free
            base["place"] = self._place_of(schedule)
            records.append(RawRecord(external_id=str(event_id), payload=base, raw_text=self._raw_text(base)))
        return records

    async def _augment_descriptions(self, session: AsyncSession, records: list[RawRecord]) -> None:
        """Best-effort upgrade of `argument` to the full `Event.description`, batched
        via aliased `event(id)` queries. Failures keep the lightweight `argument`."""
        ids = list({r.payload.get("id") for r in records if r.payload.get("id")})
        descriptions: dict[str, str] = {}
        for start in range(0, len(ids), self._DESC_CHUNK):
            chunk = ids[start : start + self._DESC_CHUNK]
            aliases = " ".join(f"e{i}: event(id:{json.dumps(eid)}){{description}}" for i, eid in enumerate(chunk))
            try:
                data = await self._post(session, {"operationName": "Desc", "variables": {}, "query": f"query Desc{{{aliases}}}"})
            except Exception:
                continue
            block = data.get("data") or {}
            for i, eid in enumerate(chunk):
                node = block.get(f"e{i}") or {}
                text = node.get("description")
                if text:
                    descriptions[eid] = text
            await asyncio.sleep(0.2)  # be gentle between detail batches

        if not descriptions:
            return
        for record in records:
            full = descriptions.get(record.payload.get("id"))
            if full:
                record.payload["description"] = self._strip_html(full)
                record.raw_text = self._raw_text(record.payload)

    # --- Field mappers -----------------------------------------------------

    def _build_dates(self, schedule: dict, today) -> list[dict]:
        if schedule.get("permanent"):
            # Fixed past sentinel (not now()) when dateStarted is missing, so the same
            # permanent event yields a STABLE date_start across fetches -> stable dedup key.
            start = self._date_to_ts(schedule.get("dateStarted")) or self._date_to_ts("2000-01-01")
            return [{"start": start, "end": _FAR_FUTURE_TS, "start_date": schedule.get("dateStarted"), "start_time": "00:00:00"}]

        # Discrete upcoming session dates are the honest representation (the soonest
        # is when you can next go). A real clock time exists only for single-showtime
        # events; everything else is all-day (-> "время уточняйте" / venue hours
        # downstream), encoded the KudaGo way (start_time 00:00:00, end = end-of-day).
        show = self._parse_dt((schedule.get("regularity") or {}).get("singleShowtime"))
        horizon = today + timedelta(days=_LOOKAHEAD_DAYS)
        rows: list[dict] = []
        for raw in schedule.get("dates") or []:
            day = self._parse_date(raw)
            if not day or day < today or day > horizon:
                continue
            if show and show.date() == day:
                start_dt, start_time, end_ts = show, show.strftime("%H:%M:%S"), None
            else:
                start_dt = datetime(day.year, day.month, day.day, tzinfo=_MSK)
                start_time = "00:00:00"
                end_ts = int(datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=_MSK).timestamp())
            rows.append({"start": int(start_dt.timestamp()), "end": end_ts, "start_date": raw, "start_time": start_time})
            if len(rows) >= self._DATES_CAP:
                break
        if rows:
            return rows

        # Fallback: a run currently in progress with no explicit in-window dates
        # (e.g. a continuously-open exhibition) -> one ongoing span -> UI "до <end>".
        start_d = self._parse_date(schedule.get("dateStarted"))
        end_d = self._parse_date(schedule.get("dateEnd"))
        if start_d and end_d and start_d <= today <= end_d:
            s = datetime(start_d.year, start_d.month, start_d.day, tzinfo=_MSK)
            e = datetime(end_d.year, end_d.month, end_d.day, 23, 59, 59, tzinfo=_MSK)
            return [{"start": int(s.timestamp()), "end": int(e.timestamp()), "start_date": schedule.get("dateStarted"), "start_time": "00:00:00"}]
        return rows

    def _place_of(self, schedule: dict) -> dict | None:
        # Single-venue events carry `onlyPlace`; multi-venue ones carry a single
        # representative `oneOfPlaces` (NOT a list). Either gives a usable pin.
        for key in ("onlyPlace", "oneOfPlaces"):
            place = schedule.get(key)
            if isinstance(place, dict):
                return self._place(place)
        return None

    @staticmethod
    def _place(place: dict) -> dict | None:
        if not isinstance(place, dict):
            return None
        coords = place.get("coordinates") if isinstance(place.get("coordinates"), dict) else {}
        lat, lon = coords.get("latitude"), coords.get("longitude")
        metro_raw = place.get("metro")
        metro = [m.get("name") for m in (metro_raw if isinstance(metro_raw, list) else []) if isinstance(m, dict) and m.get("name")]
        return {
            "id": place.get("id"),
            "title": place.get("title"),
            "address": place.get("address"),
            # Exact source coordinates — enrich uses these directly (no geocoding).
            "coords": {"lat": lat, "lon": lon} if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) else None,
            "subway": ", ".join(metro) if metro else None,
        }

    @staticmethod
    def _price(tickets: object) -> tuple[str, bool]:
        """Afisha prices are in KOPECKS — convert to a RU text field the normalizer's
        parse_price_field understands. Returns (price_text, is_free)."""
        if not isinstance(tickets, list) or not tickets:
            return "", False
        mins, maxs = [], []
        for ticket in tickets:
            price = (ticket or {}).get("price") or {}
            if isinstance(price.get("min"), (int, float)):
                mins.append(price["min"])
            if isinstance(price.get("max"), (int, float)):
                maxs.append(price["max"])
        if not mins and not maxs:
            return "", False
        lo = int(round(min(mins) / 100)) if mins else None
        hi = int(round(max(maxs) / 100)) if maxs else None
        if lo == 0 and (hi is None or hi == 0):
            return "Бесплатно", True
        if lo is not None and hi is not None and lo != hi:
            return f"от {lo} до {hi} ₽", False
        value = lo if lo is not None else hi
        return f"{value} ₽", False

    @staticmethod
    def _categories(type_obj: object) -> list:
        if not isinstance(type_obj, dict):
            return []
        out: list = []
        if type_obj.get("code"):
            out.append({"slug": type_obj["code"]})  # machine hint, e.g. "concert"
        if type_obj.get("name"):
            out.append(type_obj["name"])  # human hint, e.g. "Концерт"
        return out

    def _tags(self, tags: object) -> list:
        out: list = []
        if isinstance(tags, list):
            for tag in tags[:8]:
                if not isinstance(tag, dict):
                    continue
                if tag.get("code"):
                    out.append({"slug": tag["code"]})
                if tag.get("name"):
                    out.append(tag["name"])
        return out

    @staticmethod
    def _images(image_obj: object) -> list[dict]:
        if not isinstance(image_obj, dict):
            return []
        out: list[dict] = []
        for key in ("cover", "orig"):
            node = image_obj.get(key)
            if isinstance(node, dict) and node.get("url"):
                out.append({"image": node["url"]})
        return out

    @staticmethod
    def _abs_url(path: object) -> str:
        if not path:
            return ""
        text = str(path)
        return text if text.startswith("http") else f"https://afisha.yandex.ru{text}"

    @staticmethod
    def _strip_html(text: object) -> str:
        """Afisha descriptions occasionally embed HTML (e.g. <a> links). Flatten to
        plain text: drop tags, unescape entities, collapse whitespace."""
        if not text:
            return ""
        plain = re.sub(r"<[^>]+>", " ", str(text))
        plain = html_lib.unescape(plain)
        return re.sub(r"\s+", " ", plain).strip()

    @staticmethod
    def _raw_text(payload: dict) -> str:
        place = payload.get("place") if isinstance(payload.get("place"), dict) else {}
        parts = [
            payload.get("title") or "",
            payload.get("description") or "",
            (place or {}).get("title") or "",
            (place or {}).get("address") or "",
        ]
        return " ".join(part for part in parts if part).strip()

    # --- date helpers ------------------------------------------------------

    @staticmethod
    def _parse_date(value: object):
        if not value:
            return None
        try:
            return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
        except ValueError:
            return None

    @staticmethod
    def _parse_dt(value: object) -> datetime | None:
        """Parse a singleShowtime datetime. Requires an actual time component ('T'):
        a date-only value carries no clock, so we return None and let it fall through
        to the all-day branch instead of inventing a 00:00 showtime."""
        if not value or "T" not in str(value):
            return None
        try:
            dt = datetime.fromisoformat(str(value))
        except ValueError:
            return None
        return dt.replace(tzinfo=_MSK) if dt.tzinfo is None else dt

    def _date_to_ts(self, value: object) -> int | None:
        day = self._parse_date(value)
        if not day:
            return None
        return int(datetime(day.year, day.month, day.day, tzinfo=_MSK).timestamp())
