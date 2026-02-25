import hashlib
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

    async def fetch(self, cursor: str | None = None) -> tuple[list[RawRecord], str | None]:
        page = int(cursor) if cursor else 1
        url = f"{self.settings.kudago_base_url}/events/"
        params = {
            "lang": "ru",
            "location": self.location,
            "page": page,
            "page_size": self.page_size,
            "expand": "place,location,dates",
            "fields": f"{self._EVENT_FIELDS},is_free",
        }

        headers = {
            "User-Agent": "tg-bot-afisha/0.1 (+https://localhost)",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ru,en;q=0.8",
        }
        async with httpx.AsyncClient(timeout=20, headers=headers, follow_redirects=True) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

        results = data.get("results", [])
        records: list[RawRecord] = []
        for row in results:
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
