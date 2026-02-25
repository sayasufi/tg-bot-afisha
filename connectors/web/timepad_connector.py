import hashlib
from datetime import datetime

import httpx

from connectors.base import RawRecord
from core.config.settings import get_settings


class TimepadConnector:
    source_name = "timepad"

    def __init__(self) -> None:
        self.settings = get_settings()

    async def fetch(self, cursor: str | None = None) -> tuple[list[RawRecord], str | None]:
        url = f"{self.settings.timepad_base_url}/events"
        params: dict[str, str] = {"limit": "50", "sort": "+starts_at"}
        if cursor:
            params["starts_at_min"] = cursor

        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

        values = data.get("values", [])
        records: list[RawRecord] = []
        max_start: datetime | None = None
        for row in values:
            ext_id = str(row.get("id") or hashlib.sha256(str(row).encode()).hexdigest())
            text = " ".join(
                [
                    row.get("name", ""),
                    row.get("description_short", ""),
                    row.get("description_html", ""),
                    row.get("location", ""),
                ]
            ).strip()
            records.append(RawRecord(external_id=ext_id, payload=row, raw_text=text))
            starts_at = row.get("starts_at")
            if starts_at:
                parsed = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
                if not max_start or parsed > max_start:
                    max_start = parsed

        next_cursor = max_start.isoformat() if max_start else cursor
        return records, next_cursor
