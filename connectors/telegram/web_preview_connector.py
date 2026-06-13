import html as html_lib
import re
from datetime import datetime, timedelta, timezone

import httpx

from connectors.base import RawRecord


class TelegramWebPreviewConnector:
    """Fetches channel posts from the public t.me/s/<channel> preview page.

    Needs no Telegram account/API keys, unlike TelethonConnector. Produces the
    same payload shape and external_id format, so the two are interchangeable.
    The preview page only exposes the ~20 latest posts; with the 180s fetch
    cadence that is enough to not miss anything.
    """

    source_name = "telegram_public"
    _TEXT_LIMIT = 12000
    _LOOKBACK_DAYS = 7

    _URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
    _HASHTAG_RE = re.compile(r"#([\w\d_]+)", re.IGNORECASE)
    _MESSAGE_BLOCK_RE = re.compile(r'data-post="(?P<post>[^"]+)"(?P<body>.*?)(?=data-post="|\Z)', re.DOTALL)
    _TEXT_RE = re.compile(r'class="tgme_widget_message_text[^"]*"[^>]*>(?P<text>.*?)</div>', re.DOTALL)
    _TIME_RE = re.compile(r'<time[^>]+datetime="(?P<dt>[^"]+)"')
    _PHOTO_RE = re.compile(r"background-image:url\('(?P<url>https://[^']+)'\)")
    _BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
    _TAG_RE = re.compile(r"<[^>]+>")

    def __init__(self, channel_username: str, base_url: str = "https://t.me") -> None:
        self.channel_username = channel_username.lstrip("@").strip().lower()
        self.base_url = base_url.rstrip("/")

    @classmethod
    def _html_to_text(cls, fragment: str) -> str:
        text = cls._BR_RE.sub("\n", fragment)
        text = cls._TAG_RE.sub("", text)
        return html_lib.unescape(text).strip()

    @staticmethod
    def _first_line(text: str) -> str:
        if not text:
            return ""
        return text.strip().splitlines()[0].strip()[:200]

    def parse_page(self, page: str, min_id: int, cutoff: datetime) -> list[RawRecord]:
        records: list[RawRecord] = []
        for match in self._MESSAGE_BLOCK_RE.finditer(page):
            post = match.group("post")
            try:
                msg_id = int(post.rsplit("/", 1)[1])
            except (IndexError, ValueError):
                continue
            if msg_id <= min_id:
                continue

            body = match.group("body")
            text_match = self._TEXT_RE.search(body)
            if not text_match:
                continue
            text = self._html_to_text(text_match.group("text"))[: self._TEXT_LIMIT]
            if not text:
                continue

            published_at = ""
            time_match = self._TIME_RE.search(body)
            if time_match:
                published_at = time_match.group("dt")
                try:
                    published_dt = datetime.fromisoformat(published_at)
                    if published_dt.tzinfo and published_dt < cutoff:
                        continue
                except ValueError:
                    pass

            images = list(dict.fromkeys(m.group("url") for m in self._PHOTO_RE.finditer(body)))
            payload = {
                "id": msg_id,
                "source": "telegram_public",
                "channel_username": self.channel_username,
                "published_at": published_at or datetime.now(timezone.utc).isoformat(),
                "title": self._first_line(text),
                "description": text,
                "site_url": f"https://t.me/{self.channel_username}/{msg_id}",
                "images": images[:8],
                "url_entities": list(dict.fromkeys(self._URL_RE.findall(text))),
                "tags": list(dict.fromkeys(tag.lower() for tag in self._HASHTAG_RE.findall(text))),
            }
            records.append(
                RawRecord(
                    external_id=f"{self.channel_username}:{msg_id}",
                    payload=payload,
                    raw_text=text,
                )
            )
        return records

    async def fetch(self, cursor: str | None = None) -> tuple[list[RawRecord], str | None]:
        min_id = int(cursor) if cursor else 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._LOOKBACK_DAYS)

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10, read=30, write=10, pool=10),
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                "Accept-Language": "ru,en;q=0.8",
            },
        ) as client:
            response = await client.get(f"{self.base_url}/s/{self.channel_username}")
            response.raise_for_status()
            page = response.text

        records = self.parse_page(page, min_id=min_id, cutoff=cutoff)
        newest = max((rec.payload["id"] for rec in records), default=min_id)
        return records, str(newest) if newest else cursor
