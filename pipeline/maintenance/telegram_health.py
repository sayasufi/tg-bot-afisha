"""Retire Telegram channels that have gone dark.

Venue channels close, move or simply stop (Powerhouse shut down after 13 years, Mutabor→Arma relocated,
a fest channel whose last post is from 2022). A dead channel yields no events and just wastes fetches,
so this daily sweep deactivates it and keeps the active set live.

Conservative — only deactivates on a DEFINITIVE signal:
  * a reachable t.me/s/ preview whose newest post is older than `stale_days`, or
  * a "gone" preview: 301/302 (s/ redirects to t.me/<u> → web-preview disabled, can't ingest anyway),
    404 (no channel), or a page with no posts at all.
A transient network error is SKIPPED (never kill a live channel on a blip).
"""
import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select, update

from core.config.settings import get_settings
from core.db.models import TelegramChannel
from core.db.session import WorkerAsyncSessionLocal

log = logging.getLogger(__name__)
_TIME_RE = re.compile(r'<time[^>]+datetime="([^"]+)"')
# The public t.me/<channel> page shows the FULL count: <div class="tgme_page_extra">12 345 subscribers</div>
# (thousands separated by space / nbsp / narrow-nbsp). The s/ feed header only carries an abbreviated
# "12.3K", so we hit the plain page for precision.
_SUBS_RE = re.compile(r'tgme_page_extra"[^>]*>\s*([\d\s  .,]+?)\s*subscriber', re.IGNORECASE)
_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def _parse_newest(html: str) -> datetime | None:
    """Newest post datetime on a t.me/s/ preview page (max over its <time datetime="..."> tags)."""
    out: list[datetime] = []
    for raw in _TIME_RE.findall(html):
        try:
            out.append(datetime.fromisoformat(raw))
        except ValueError:
            continue
    return max(out) if out else None


async def _probe(client: httpx.AsyncClient, username: str) -> tuple[str, object]:
    """('ok', datetime) | ('preview_off', reason) | ('gone', reason) | ('error', reason). preview_off is
    kept SEPARATE from gone: the channel may be perfectly alive but with web-preview disabled, which the
    Telethon fallback can still read — so we only retire it when there is no Telethon session."""
    try:
        r = await client.get(f"https://t.me/s/{username}")
    except Exception as exc:  # network/timeout — transient, don't act on it
        return "error", repr(exc)[:60]
    if r.status_code in (301, 302):
        return "preview_off", "preview disabled"
    if r.status_code == 404:
        return "gone", "no channel"
    if r.status_code != 200:
        return "error", f"http {r.status_code}"
    newest = _parse_newest(r.text)
    return ("ok", newest) if newest else ("gone", "no posts")


async def prune_stale_channels(stale_days: int = 60) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=stale_days)
    # A preview-off channel is still ingestable via the Telethon fallback, so retire it ONLY when no
    # session is configured (then HTTP is the only transport and it genuinely can't be read).
    s = get_settings()
    telethon_available = bool(s.telethon_api_id and s.telethon_api_hash and s.telethon_session)
    async with WorkerAsyncSessionLocal() as db:
        usernames = (
            await db.execute(select(TelegramChannel.username).where(TelegramChannel.is_active.is_(True)))
        ).scalars().all()
    deactivate: list[str] = []
    timeout = httpx.Timeout(connect=10, read=20, write=10, pool=10)
    # follow_redirects=False so a disabled-preview 302 is detected (not silently followed); SSRF-safe.
    async with httpx.AsyncClient(timeout=timeout, headers=_UA, follow_redirects=False) as client:
        for u in usernames:
            status, info = await _probe(client, u)
            if (
                status == "gone"
                or (status == "ok" and isinstance(info, datetime) and info < cutoff)
                or (status == "preview_off" and not telethon_available)
            ):
                deactivate.append(u)
    if deactivate:
        async with WorkerAsyncSessionLocal() as db:
            await db.execute(
                update(TelegramChannel).where(TelegramChannel.username.in_(deactivate)).values(is_active=False)
            )
            await db.commit()
        log.info("telegram_prune deactivated %s", deactivate)
    return {"checked": len(usernames), "deactivated": deactivate}


async def _fetch_subs(client: httpx.AsyncClient, username: str) -> int | None:
    try:
        r = await client.get(f"https://t.me/{username}")
    except Exception:  # transient — just skip this channel this round
        return None
    if r.status_code != 200:
        return None
    m = _SUBS_RE.search(r.text)
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(1))
    return int(digits) if digits else None


async def refresh_subscribers() -> dict:
    """Cache each active channel's subscriber count in ref.telegram_channels.subscribers (reach signal).
    Concurrent + polite; a channel that doesn't yield a count (private/preview-off/transient) keeps its
    last value. Returns checked/updated + the min/median/max so the smallest channels are visible."""
    async with WorkerAsyncSessionLocal() as db:
        usernames = (
            await db.execute(select(TelegramChannel.username).where(TelegramChannel.is_active.is_(True)))
        ).scalars().all()
    counts: dict[str, int] = {}
    sem = asyncio.Semaphore(8)
    timeout = httpx.Timeout(connect=10, read=20, write=10, pool=10)
    async with httpx.AsyncClient(timeout=timeout, headers=_UA, follow_redirects=True) as client:
        async def one(u: str) -> None:
            async with sem:
                c = await _fetch_subs(client, u)
                if c is not None:
                    counts[u] = c
        await asyncio.gather(*(one(u) for u in usernames))
    if counts:
        async with WorkerAsyncSessionLocal() as db:
            for u, c in counts.items():
                await db.execute(
                    update(TelegramChannel).where(TelegramChannel.username == u).values(subscribers=c)
                )
            await db.commit()
    vals = sorted(counts.values())
    return {
        "checked": len(usernames),
        "updated": len(counts),
        "min": vals[0] if vals else None,
        "median": vals[len(vals) // 2] if vals else None,
        "max": vals[-1] if vals else None,
    }
