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
from sqlalchemy import select, text, update

from core.config.settings import get_settings
from core.db.models import TelegramChannel
from core.db.session import WorkerAsyncSessionLocal

log = logging.getLogger(__name__)
# Reach floor: below this many subscribers a channel is near-empty/fake, so the daily subscriber refresh
# retires it. Kept LOW (100, was 500) — for an EVENT SOURCE the value is "posts events" (the 60-day-silence
# prune already gates that), NOT popularity: a 200-sub regional venue (small-city theatre, district ДК,
# gallery) still posts real events we'd otherwise miss, and 500 wrongly retired legit venues (Дворец
# молодёжи, Манеж Казань). NULL count (unfetchable / throttled) is left alone.
_MIN_SUBSCRIBERS = 100
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
    """Cache each active channel's subscriber count (reach signal) AND enforce the _MIN_SUBSCRIBERS floor:
    channels that come back below it are retired (is_active=False). Concurrent + polite; a channel that
    doesn't yield a count (private/preview-off/transient) keeps its last value and is NOT retired."""
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
    retired: list[str] = []
    if counts:
        async with WorkerAsyncSessionLocal() as db:
            for u, c in counts.items():
                await db.execute(
                    update(TelegramChannel).where(TelegramChannel.username == u).values(subscribers=c)
                )
            await db.commit()
            # Reach floor — retire channels now known to be below the threshold (NULL = unknown → kept).
            res = await db.execute(
                update(TelegramChannel)
                .where(TelegramChannel.is_active.is_(True), TelegramChannel.subscribers < _MIN_SUBSCRIBERS)
                .values(is_active=False)
                .returning(TelegramChannel.username)
            )
            retired = list(res.scalars().all())
            await db.commit()
            if retired:
                log.info("telegram_subscribers retired %s below %s", retired, _MIN_SUBSCRIBERS)
    vals = sorted(counts.values())
    return {
        "checked": len(usernames),
        "updated": len(counts),
        "min_kept": next((v for v in vals if v >= _MIN_SUBSCRIBERS), None),
        "median": vals[len(vals) // 2] if vals else None,
        "max": vals[-1] if vals else None,
        "retired_below_min": retired,
        "min_subscribers": _MIN_SUBSCRIBERS,
    }


# Event-yield floor: the prunes above retire channels that are DARK / preview-off / tiny — but a channel can
# be live, posting, ≥100 subs and STILL never give us an event (it posts only non-events, or always-past
# dates, or text we can't extract). For an event SOURCE that's dead weight forever. So once a channel has had
# a fair chance — its source is old enough AND we've actually PROCESSED enough of its posts — yet produced
# ZERO event candidates, retire it. Conservative thresholds so a new/seasonal venue isn't cut prematurely.
_YIELD_GRACE_DAYS = 21
_YIELD_MIN_PROCESSED = 15
# Source name mirrors ensure_source: "telegram_public:<username, @/space-trimmed, lowercased>".
_SRC_NAME = "'telegram_public:' || lower(btrim(tc.username, '@ '))"


async def retire_zero_yield_channels() -> dict:
    """Retire active venue channels that have been fetched ≥`_YIELD_GRACE_DAYS` ago AND had
    ≥`_YIELD_MIN_PROCESSED` posts normalised, yet produced 0 event candidates — i.e. proven NOT an event
    source. NULL-yield with too-few processed posts (still draining) or a too-young source is left alone."""
    async with WorkerAsyncSessionLocal() as db:
        res = await db.execute(text(
            "UPDATE ref.telegram_channels tc SET is_active = false WHERE tc.is_active "
            f"  AND EXISTS (SELECT 1 FROM ref.sources s WHERE s.name = {_SRC_NAME} "
            "              AND s.created_at < now() - make_interval(days => :grace)) "
            "  AND (SELECT count(*) FROM events.raw_events re JOIN ref.sources s2 "
            f"       ON s2.source_id = re.source_id AND s2.name = {_SRC_NAME} "
            "       WHERE re.processed_hash IS NOT NULL) >= :minproc "
            "  AND NOT EXISTS (SELECT 1 FROM events.event_candidates c "
            "                  JOIN events.raw_events re2 ON re2.raw_id = c.raw_id "
            f"                  JOIN ref.sources s3 ON s3.source_id = re2.source_id AND s3.name = {_SRC_NAME}) "
            "RETURNING tc.username"
        ), {"grace": _YIELD_GRACE_DAYS, "minproc": _YIELD_MIN_PROCESSED})
        retired = list(res.scalars().all())
        await db.commit()
    if retired:
        log.info("telegram_yield retired %s (0 candidates after %sd / %s+ processed posts)",
                 retired, _YIELD_GRACE_DAYS, _YIELD_MIN_PROCESSED)
    return {"retired_zero_yield": retired, "count": len(retired)}
