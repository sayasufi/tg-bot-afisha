from datetime import datetime, timezone

from telethon import TelegramClient

from connectors.base import RawRecord
from core.config.settings import get_settings


class TelethonConnector:
    source_name = "telegram_public"

    def __init__(self, channel_username: str) -> None:
        self.settings = get_settings()
        self.channel_username = channel_username

    async def fetch(self, cursor: str | None = None) -> tuple[list[RawRecord], str | None]:
        if not self.settings.telethon_api_id or not self.settings.telethon_api_hash:
            return [], cursor

        min_id = int(cursor) if cursor else 0
        records: list[RawRecord] = []
        newest = min_id
        async with TelegramClient(self.settings.telethon_session, self.settings.telethon_api_id, self.settings.telethon_api_hash) as client:
            async for msg in client.iter_messages(self.channel_username, min_id=min_id, limit=100):
                if not msg.message:
                    continue
                payload = {
                    "id": msg.id,
                    "date": msg.date.isoformat() if msg.date else datetime.now(timezone.utc).isoformat(),
                    "text": msg.message,
                    "views": msg.views,
                    "forwards": msg.forwards,
                }
                records.append(RawRecord(external_id=f"{self.channel_username}:{msg.id}", payload=payload, raw_text=msg.message))
                newest = max(newest, msg.id)
        return records, str(newest) if newest else cursor
