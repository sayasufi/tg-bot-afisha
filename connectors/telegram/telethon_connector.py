import re
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient

from connectors.base import RawRecord
from core.config.settings import get_settings


class TelethonConnector:
    source_name = "telegram_public"
    _URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
    _HASHTAG_RE = re.compile(r"#([\w\d_]+)", re.IGNORECASE)
    _TEXT_LIMIT = 12000
    _LOOKBACK_DAYS = 7

    def __init__(self, channel_username: str) -> None:
        self.settings = get_settings()
        self.channel_username = channel_username

    @staticmethod
    def _first_line(text: str) -> str:
        if not text:
            return ""
        line = text.strip().splitlines()[0].strip()
        return line[:200]

    def _message_url(self, msg_id: int) -> str:
        channel = self.channel_username.lstrip("@")
        return f"https://t.me/{channel}/{msg_id}" if channel else ""

    def _build_payload(self, msg) -> dict:
        text = (msg.message or "").strip()
        urls = list(dict.fromkeys(self._URL_RE.findall(text)))
        tags = [tag.lower() for tag in self._HASHTAG_RE.findall(text)]
        payload = {
            "id": msg.id,
            "source": "telegram_public",
            "channel_username": self.channel_username.lstrip("@"),
            "published_at": msg.date.isoformat() if msg.date else datetime.now(timezone.utc).isoformat(),
            "title": self._first_line(text),
            "description": text[: self._TEXT_LIMIT],
            "site_url": self._message_url(msg.id),
            "images": [],
            "url_entities": urls,
            "tags": list(dict.fromkeys(tags)),
            "views": msg.views,
            "forwards": msg.forwards,
        }
        return payload

    async def fetch(self, cursor: str | None = None) -> tuple[list[RawRecord], str | None]:
        if not self.settings.telethon_api_id or not self.settings.telethon_api_hash:
            return [], cursor

        min_id = int(cursor) if cursor else 0
        min_date = datetime.now(timezone.utc) - timedelta(days=self._LOOKBACK_DAYS)
        records: list[RawRecord] = []
        newest = min_id
        async with TelegramClient(self.settings.telethon_session, self.settings.telethon_api_id, self.settings.telethon_api_hash) as client:
            async for msg in client.iter_messages(self.channel_username, min_id=min_id, limit=100):
                if not msg.message:
                    continue
                if msg.date and msg.date < min_date:
                    # iter_messages returns messages from newest to oldest, so we can stop here.
                    break
                payload = self._build_payload(msg)
                records.append(
                    RawRecord(
                        external_id=f"{self.channel_username}:{msg.id}",
                        payload=payload,
                        raw_text=payload["description"],
                    )
                )
                newest = max(newest, msg.id)
        return records, str(newest) if newest else cursor
