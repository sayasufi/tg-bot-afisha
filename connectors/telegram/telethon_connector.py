"""Read PUBLIC channels with a Telethon user session — WITHOUT joining them.

`iter_messages(<public-username>)` resolves a public channel and reads its history for any logged-in
account, no membership required. Unlike the web-preview scraper this gets the FULL post text (the
preview truncates long posts at «…») and the whole history (not just the preview window). Photos are
downloaded once and cached in MinIO so cards keep their image. Off unless a session string is set
(settings.telethon_session) — the connector toggle in fetch.py then prefers it over the scraper.
"""
import logging
import re
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient
from telethon.sessions import StringSession

from connectors.base import RawRecord
from core.config.settings import get_settings

log = logging.getLogger(__name__)


class TelethonConnector:
    source_name = "telegram_public"
    _URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
    _HASHTAG_RE = re.compile(r"#([\w\d_]+)", re.IGNORECASE)
    _TEXT_LIMIT = 12000
    _LOOKBACK_DAYS = 7
    # First pull (no cursor) reaches back further so events announced weeks ahead are captured.
    _BACKFILL_LOOKBACK_DAYS = 60
    _LIMIT = 120
    _BACKFILL_LIMIT = 500

    def __init__(self, channel_username: str) -> None:
        self.settings = get_settings()
        self.channel_username = channel_username

    @staticmethod
    def _first_line(text: str) -> str:
        if not text:
            return ""
        return text.strip().splitlines()[0].strip()[:200]

    def _message_url(self, msg_id: int) -> str:
        channel = self.channel_username.lstrip("@")
        return f"https://t.me/{channel}/{msg_id}" if channel else ""

    def _build_payload(self, msg) -> dict:
        text = (msg.message or "").strip()
        urls = list(dict.fromkeys(self._URL_RE.findall(text)))
        tags = [tag.lower() for tag in self._HASHTAG_RE.findall(text)]
        return {
            "id": msg.id,
            "source": "telegram_public",
            "channel_username": self.channel_username.lstrip("@"),
            "published_at": msg.date.isoformat() if msg.date else datetime.now(timezone.utc).isoformat(),
            "title": self._first_line(text),
            "description": text[: self._TEXT_LIMIT],
            "site_url": self._message_url(msg.id),
            "images": [],  # photos are downloaded lazily — only for posts that become events
            "has_photo": bool(getattr(msg, "photo", None)),  # the lazy media flow keys off this
            "url_entities": urls,
            "tags": list(dict.fromkeys(tags)),
            "views": getattr(msg, "views", None),
            "forwards": getattr(msg, "forwards", None),
        }

    async def fetch(self, cursor: str | None = None, client: TelegramClient | None = None) -> tuple[list[RawRecord], str | None]:
        """`client` lets the caller share ONE Telethon client across channels (multiplexed over a
        single connection) so channels can be fetched concurrently without 16 clients on one session."""
        if not (self.settings.telethon_api_id and self.settings.telethon_api_hash and self.settings.telethon_session):
            return [], cursor

        min_id = int(cursor) if cursor else 0
        backfill = min_id == 0
        lookback = self._BACKFILL_LOOKBACK_DAYS if backfill else self._LOOKBACK_DAYS
        limit = self._BACKFILL_LIMIT if backfill else self._LIMIT
        min_date = datetime.now(timezone.utc) - timedelta(days=lookback)

        own = client is None
        if own:
            client = TelegramClient(StringSession(self.settings.telethon_session), self.settings.telethon_api_id, self.settings.telethon_api_hash)
            await client.connect()
        try:
            if not await client.is_user_authorized():
                log.warning("telethon_not_authorized — set TELETHON_SESSION via scripts/telethon_login.py")
                return [], cursor
            records: list[RawRecord] = []
            newest = min_id
            async for msg in client.iter_messages(self.channel_username, min_id=min_id, limit=limit):
                if not msg.message:  # skip media-only / service messages (album extra frames, etc.)
                    continue
                if msg.date and msg.date < min_date:
                    break  # newest→oldest, so once we cross the window we're done
                payload = self._build_payload(msg)
                records.append(RawRecord(external_id=f"{self.channel_username}:{msg.id}", payload=payload, raw_text=payload["description"]))
                newest = max(newest, msg.id)
            return records, str(newest) if newest else cursor
        finally:
            if own:
                await client.disconnect()
