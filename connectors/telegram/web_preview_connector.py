import html as html_lib
import re
from datetime import datetime, timedelta, timezone

import httpx

from connectors.base import RawRecord


class PreviewUnavailable(Exception):
    """t.me/s/<channel> can't be read over plain HTTP — web-preview is disabled (s/ redirects to the
    private page) or the channel shows no posts at all. The fetch caller falls back to Telethon."""


class TelegramWebPreviewConnector:
    """Fetches channel posts from the public t.me/s/<channel> preview page.

    Needs no Telegram account/API keys, unlike TelethonConnector. Produces the
    same payload shape and external_id format, so the two are interchangeable.

    A preview page shows ~15-20 posts; `?before=<msg_id>` pages further back. On a
    first fetch (no cursor) we page back to capture announcements made weeks ahead
    of the event — venues post far in advance, so a single latest page misses most
    upcoming events. Once a cursor exists, fetches read just the latest page for new
    posts (the 180s cadence keeps it current).
    """

    source_name = "telegram_public"
    _TEXT_LIMIT = 12000
    _LOOKBACK_DAYS = 7
    # First-fetch backfill: walk further back so a 26 Jun concert announced on 5 Jun (a post older than
    # the 7-day incremental window) still gets ingested. The post-past-event gate drops anything whose
    # event has actually passed, so a wide post window is safe.
    _BACKFILL_PAGES = 8
    _BACKFILL_LOOKBACK_DAYS = 14
    # Full-text resolve budget for truncated («…») posts. `_RESOLVE_LOOKBACK` bounds the per-post
    # single-page GETs (msgid + up to 3 below it, to catch an album's caption on its first grouped
    # message); `_MAX_RESOLVES_PER_FETCH` caps how many truncated posts we resolve in one pass so a
    # first backfill (8 pages, many clipped posts) can't fan out into ~1000 sequential single-post
    # GETs. Anything over budget keeps its clipped preview text — still ingestible, just shorter.
    _RESOLVE_LOOKBACK = 3
    _MAX_RESOLVES_PER_FETCH = 40

    _URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
    _HASHTAG_RE = re.compile(r"#([\w\d_]+)", re.IGNORECASE)
    _MESSAGE_BLOCK_RE = re.compile(r'data-post="(?P<post>[^"]+)"(?P<body>.*?)(?=data-post="|\Z)', re.DOTALL)
    _TEXT_RE = re.compile(r'class="tgme_widget_message_text[^"]*"[^>]*>(?P<text>.*?)</div>', re.DOTALL)
    _TIME_RE = re.compile(r'<time[^>]+datetime="(?P<dt>[^"]+)"')
    _PHOTO_RE = re.compile(r"background-image:url\('(?P<url>https://[^']+)'\)")
    _BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
    _TAG_RE = re.compile(r"<[^>]+>")
    # The single-post page carries the FULL message text in og:description (the s/ preview truncates
    # long posts with a trailing «…»). Match either attribute order.
    _OG_RE = re.compile(r'<meta[^>]+property="og:description"[^>]+content="([^"]*)"', re.DOTALL)
    _OG_RE2 = re.compile(r'<meta[^>]+content="([^"]*)"[^>]+property="og:description"', re.DOTALL)
    _TRUNCATED_SUFFIX = "…"  # «…» that Telegram appends to a clipped preview

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

    def _page_floor(self, page: str) -> tuple[int | None, datetime | None]:
        """Lowest message id and oldest post datetime on a preview page — drives ?before pagination and
        tells us when we've paged past the lookback window."""
        ids: list[int] = []
        for match in self._MESSAGE_BLOCK_RE.finditer(page):
            try:
                ids.append(int(match.group("post").rsplit("/", 1)[1]))
            except (IndexError, ValueError):
                continue
        dts: list[datetime] = []
        for match in self._TIME_RE.finditer(page):
            try:
                dts.append(datetime.fromisoformat(match.group("dt")))
            except ValueError:
                continue
        return (min(ids) if ids else None), (min(dts) if dts else None)

    def _page_max_id(self, page: str) -> int | None:
        """Highest message id present on a preview page, INCLUDING posts older than the cutoff.
        Advancing the cursor to this (not just to the newest kept record) keeps a dormant channel
        — one whose latest posts all pre-date the lookback window — from being re-scanned in full
        every 180s: without it `newest` never moves off the old cursor and each run re-pages back."""
        ids: list[int] = []
        for match in self._MESSAGE_BLOCK_RE.finditer(page):
            try:
                ids.append(int(match.group("post").rsplit("/", 1)[1]))
            except (IndexError, ValueError):
                continue
        return max(ids) if ids else None

    def _og_description(self, page: str) -> str:
        for rx in (self._OG_RE, self._OG_RE2):
            m = rx.search(page)
            if m:
                return html_lib.unescape(m.group(1)).strip()
        return ""

    async def _resolve_full_text(self, client: httpx.AsyncClient, msgid: int, truncated: str) -> str | None:
        """A long post is clipped in the s/ preview; the single-post page's og:description carries the
        FULL text. For an album the text sits on the FIRST grouped message (a lower id than the one the
        feed tags), so scan a small window down from msgid and accept the og whose text starts with the
        truncated prefix — that guard stops us grabbing a neighbouring post.

        The window is deliberately shallow (`_RESOLVE_LOOKBACK`): the non-album case hits on the first
        GET (msgid itself) and an album's caption sits only 1-3 messages back, so the old 9-deep scan
        just burned requests. A miss now costs at most `_RESOLVE_LOOKBACK + 1` GETs instead of 9."""
        prefix = " ".join(truncated.rstrip("… \n").split())[:24]
        if not prefix:
            return None
        for mid in range(msgid, max(msgid - self._RESOLVE_LOOKBACK - 1, 0), -1):
            try:
                r = await client.get(f"{self.base_url}/{self.channel_username}/{mid}")
            except httpx.HTTPError:
                continue
            if r.status_code != 200:
                continue
            og = self._og_description(r.text)
            if og and " ".join(og.split()).startswith(prefix):
                return og
        return None

    async def fetch(self, cursor: str | None = None, max_pages: int | None = None, client=None) -> tuple[list[RawRecord], str | None]:
        # `client` is accepted for a uniform call signature with TelethonConnector; web-preview is
        # plain HTTP and ignores it (each fetch opens its own client).
        min_id = int(cursor) if cursor else 0
        backfill = min_id == 0
        if max_pages is None:
            max_pages = self._BACKFILL_PAGES if backfill else 1
        lookback = self._BACKFILL_LOOKBACK_DAYS if backfill else self._LOOKBACK_DAYS
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback)

        collected: dict[str, RawRecord] = {}
        newest = min_id
        before: int | None = None
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10, read=30, write=10, pool=10),
            follow_redirects=False,  # SSRF guard: don't follow redirects into internal space
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                "Accept-Language": "ru,en;q=0.8",
            },
        ) as client:
            for page_idx in range(max(1, max_pages)):
                url = f"{self.base_url}/s/{self.channel_username}"
                if before is not None:
                    url += f"?before={before}"
                response = await client.get(url)
                # Web-preview disabled → s/ 301/302-redirects to the private page; signal so the caller
                # falls back to Telethon instead of silently ingesting nothing.
                if response.status_code in (301, 302):
                    raise PreviewUnavailable(self.channel_username)
                response.raise_for_status()
                page = response.text

                page_min, oldest_dt = self._page_floor(page)
                # Zero messages on the FIRST page = preview off / dead channel (an incremental fetch with
                # no NEW posts still shows the OLD ones, so page_min is set — that's not unavailable).
                if page_idx == 0 and page_min is None:
                    raise PreviewUnavailable(self.channel_username)

                # Advance the cursor to the newest message SEEN — even ones filtered out by the
                # cutoff — so a dormant channel (latest posts all older than the lookback window)
                # doesn't re-page from scratch every run. parse_page only yields kept records, so
                # without this `newest` would stay at the old cursor for a channel with no fresh
                # in-window posts.
                page_max = self._page_max_id(page)
                if page_max is not None and page_max > min_id:
                    newest = max(newest, page_max)

                for rec in self.parse_page(page, min_id=min_id, cutoff=cutoff):
                    collected[rec.external_id] = rec
                    newest = max(newest, rec.payload["id"])

                if page_min is None or (before is not None and page_min >= before):
                    break  # empty page, or pagination made no progress
                before = page_min
                if oldest_dt is not None and oldest_dt.tzinfo and oldest_dt < cutoff:
                    break  # paged past the lookback window — stop

            records = list(collected.values())
            # A long post is clipped in the s/ preview («…»); pull its full text from the single-post
            # og:description so multi-event schedules and detailed posts aren't silently truncated.
            # Resolve NEWEST-first and cap the count per pass (_MAX_RESOLVES_PER_FETCH): a first
            # backfill can hold dozens of clipped posts, and each resolve is several single-post GETs
            # — without a cap that fans out into hundreds/~1000 requests to t.me on the first fetch.
            resolve_budget = self._MAX_RESOLVES_PER_FETCH
            resolved: list[RawRecord] = []
            for rec in sorted(records, key=lambda r: int(r.payload["id"]), reverse=True):
                if resolve_budget > 0 and rec.raw_text.rstrip().endswith(self._TRUNCATED_SUFFIX):
                    resolve_budget -= 1
                    full = await self._resolve_full_text(client, int(rec.payload["id"]), rec.raw_text)
                    if full and len(full) > len(rec.raw_text):
                        text = full[: self._TEXT_LIMIT]
                        rec = RawRecord(
                            external_id=rec.external_id,
                            payload={**rec.payload, "title": self._first_line(text), "description": text},
                            raw_text=text,
                        )
                resolved.append(rec)
            records = resolved

        return records, str(newest) if newest else cursor
