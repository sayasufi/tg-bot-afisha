import hashlib
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx

from connectors.base import RawRecord
from core.config.settings import get_settings


class KudaGoConnector:
    source_name = "kudago"
    # Only fields required by current MVP pipeline:
    # normalization -> candidate extraction -> dedup -> map/search API.
    _EVENT_FIELDS = (
        "id,title,short_title,description,body_text,"
        "dates,place,location,site_url,images,price,age_restriction,categories,tags"
    )
    _BODY_TEXT_LIMIT = 12000
    _LOOKAHEAD_DAYS = 30

    def __init__(self, location: str = "msk", page_size: int = 100) -> None:
        self.settings = get_settings()
        self.location = location
        self.page_size = page_size

    def _trim_payload(self, row: dict) -> dict:
        place = row.get("place") if isinstance(row.get("place"), dict) else None
        if place:
            place = {
                "title": place.get("title"),
                "address": place.get("address"),
                "coords": place.get("coords"),
            }

        location = row.get("location") if isinstance(row.get("location"), dict) else None
        if location:
            location = {
                "slug": location.get("slug"),
                "name": location.get("name"),
                "timezone": location.get("timezone"),
                "coords": location.get("coords"),
            }

        dates = row.get("dates")
        trimmed_dates: list[dict] = []
        if isinstance(dates, list):
            for item in dates[:8]:
                if not isinstance(item, dict):
                    continue
                trimmed_dates.append(
                    {
                        "start": item.get("start"),
                        "end": item.get("end"),
                        "start_date": item.get("start_date"),
                        "start_time": item.get("start_time"),
                        "end_date": item.get("end_date"),
                        "end_time": item.get("end_time"),
                    }
                )

        images = row.get("images")
        trimmed_images: list[dict | str] = []
        if isinstance(images, list):
            for item in images[:8]:
                if isinstance(item, dict):
                    trimmed_images.append({"image": item.get("image"), "source": item.get("source")})
                elif isinstance(item, str):
                    trimmed_images.append(item)

        body_text = row.get("body_text")
        body_text_trimmed = body_text[: self._BODY_TEXT_LIMIT] if isinstance(body_text, str) else ""

        payload = {
            "id": row.get("id"),
            "title": row.get("title"),
            "short_title": row.get("short_title"),
            "description": row.get("description"),
            "body_text": body_text_trimmed,
            "dates": trimmed_dates,
            "place": place,
            "location": location,
            "site_url": row.get("site_url"),
            "images": trimmed_images,
            "price": row.get("price"),
            "is_free": row.get("is_free"),
            "age_restriction": row.get("age_restriction"),
            "categories": row.get("categories"),
            "tags": row.get("tags"),
        }
        if not payload["site_url"] and row.get("slug"):
            payload["site_url"] = f"https://kudago.com/{self.location}/event/{row.get('slug')}/"
        return payload

    @staticmethod
    def _safe_ts_to_dt(value: object) -> datetime | None:
        if value in (None, ""):
            return None
        try:
            ts = int(value)
        except (TypeError, ValueError):
            return None
        if ts <= 0:
            return None
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    def _is_in_window(self, row: dict, now: datetime, until: datetime) -> bool:
        dates = row.get("dates")
        if not isinstance(dates, list) or not dates:
            return False

        for item in dates:
            if not isinstance(item, dict):
                continue
            start_dt = self._safe_ts_to_dt(item.get("start"))
            end_dt = self._safe_ts_to_dt(item.get("end"))
            # Keep events relevant for the next 30 days:
            # - normal case: known start within [now; now+30d]
            # - ongoing case: started earlier but still active now/soon (end in window)
            # - sentinel case: invalid start but valid end in window
            if start_dt and now <= start_dt <= until:
                return True
            if end_dt and now <= end_dt <= until:
                return True
            if start_dt and end_dt and start_dt < now and end_dt >= now:
                return True
        return False

    async def fetch(self, cursor: str | None = None) -> tuple[list[RawRecord], str | None]:
        page = int(cursor) if cursor else 1
        now = datetime.now(timezone.utc)
        until = now + timedelta(days=self._LOOKAHEAD_DAYS)
        url = f"{self.settings.kudago_base_url}/events/"
        params = {
            "lang": "ru",
            "location": self.location,
            "page": page,
            "page_size": self.page_size,
            "actual_since": int(now.timestamp()),
            "actual_until": int(until.timestamp()),
            "expand": "place,location,dates",
            "fields": f"{self._EVENT_FIELDS},is_free",
        }

        headers = {
            "User-Agent": "tg-bot-afisha/0.1 (+https://localhost)",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ru,en;q=0.8",
        }
        timeout = httpx.Timeout(connect=10.0, read=60.0, write=20.0, pool=20.0)
        async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

        results = data.get("results", [])
        records: list[RawRecord] = []
        for row in results:
            if not self._is_in_window(row, now, until):
                continue
            payload = self._trim_payload(row)
            ext_id = str(payload.get("id") or hashlib.sha256(str(payload).encode()).hexdigest())
            title = payload.get("title", "") or payload.get("short_title", "")
            description = payload.get("description", "") or payload.get("body_text", "")
            place = payload.get("place", {}) if isinstance(payload.get("place"), dict) else {}
            raw_text = " ".join([title, description, place.get("title", ""), place.get("address", "")]).strip()
            records.append(RawRecord(external_id=ext_id, payload=payload, raw_text=raw_text))

        next_cursor = str(page)
        next_link = data.get("next")
        if next_link:
            query = parse_qs(urlparse(str(next_link)).query)
            next_page = query.get("page", [None])[0]
            next_cursor = str(next_page) if next_page else str(page + 1)
        elif results:
            next_cursor = str(page + 1)

        return records, next_cursor
