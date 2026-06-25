"""Telethon-источник — точные метрики ПРЯМО из Telegram (безлимит, без тарифов и капчи).

- channel_metrics: подписчики (participants_count), средний охват по последним постам, ER, частота.
- recommendations: «похожие каналы» от самого Telegram (GetChannelRecommendations) — бесплатный
  граф-крауль для discovery чистой афиши от сидов (решает «264 мало» без мусора Telega).
"""
from __future__ import annotations

import asyncio
import logging

from core.config.settings import get_settings

from apps.worker.worker.adstat.service import persist_snapshots, upsert_targets

log = logging.getLogger(__name__)


def _make_client():
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    s = get_settings()
    if not (s.telethon_api_id and s.telethon_api_hash and s.telethon_session):
        return None
    return TelegramClient(StringSession(s.telethon_session), s.telethon_api_id, s.telethon_api_hash)


async def _metrics(client, username: str) -> dict:
    from telethon.tl.functions.channels import GetFullChannelRequest

    u = username.lstrip("@")
    try:
        ent = await client.get_entity(u)
        full = await client(GetFullChannelRequest(ent))
        subs = getattr(full.full_chat, "participants_count", None)
    except Exception as e:  # noqa: BLE001
        return {"source": "telethon", "username": u, "error": str(e)[:140]}

    views, dates, fwd = [], [], []
    try:
        async for msg in client.iter_messages(ent, limit=20):
            if getattr(msg, "views", None):
                views.append(msg.views)
            if getattr(msg, "forwards", None):
                fwd.append(msg.forwards)
            if msg.date:
                dates.append(msg.date)
    except Exception:  # noqa: BLE001
        pass

    avg_reach = int(sum(views) / len(views)) if views else None
    er = round(avg_reach / subs * 100, 2) if avg_reach and subs else None
    freq = None
    if len(dates) >= 2:
        span = (dates[0] - dates[-1]).total_seconds() / 86400
        if span > 0:
            freq = round(len(dates) / span * 7, 1)
    return {
        "source": "telethon",
        "username": (getattr(ent, "username", None) or u),
        "peer_id": getattr(ent, "id", None),
        "title": getattr(ent, "title", None),
        "subscribers": subs, "avg_reach": avg_reach, "er": er,
        "raw": {"posts_per_week": freq, "samples": len(views),
                "avg_forwards": int(sum(fwd) / len(fwd)) if fwd else None},
    }


async def _recs(client, username: str) -> list[str]:
    from telethon.tl.functions.channels import GetChannelRecommendationsRequest

    try:
        ent = await client.get_entity(username.lstrip("@"))
        res = await client(GetChannelRecommendationsRequest(channel=ent))
        return [c.username for c in getattr(res, "chats", []) if getattr(c, "username", None)]
    except Exception as e:  # noqa: BLE001
        log.warning("telethon recs %s: %s", username, e)
        return []


def _afisha_seeds(limit: int = 60) -> list[str]:
    """Сиды для крауля — уже найденные афиша-каналы (Telemetr, city проставлен)."""
    from sqlalchemy import select

    from core.db.models.adstat import AdTarget
    from core.db.session import SessionLocal

    with SessionLocal() as db:
        return list(db.execute(
            select(AdTarget.username).where(AdTarget.city.isnot(None)).limit(limit)
        ).scalars().all())


async def _crawl(seeds: list[str], max_channels: int, sink=None) -> int:
    """Interleaved BFS по рекомендациям: на каждый канал снимаем метрики + тянем «похожих»,
    батч (20) сбрасываем в БД через sink — инкрементально, устойчиво к обрыву/таймауту."""
    client = _make_client()
    if client is None:
        log.warning("telethon: нет TELETHON_SESSION/api — пропуск")
        return 0
    await client.connect()
    try:
        if not await client.is_user_authorized():
            log.warning("telethon: сессия не авторизована")
            return 0
        found: set[str] = set()
        queue = list(dict.fromkeys(s.lstrip("@") for s in seeds))
        batch: list[dict] = []
        done = 0
        while queue and len(found) < max_channels:
            u = queue.pop(0)
            if u in found:
                continue
            found.add(u)
            m = await _metrics(client, u)
            if not m.get("error"):
                batch.append(m)
            for r in await _recs(client, u):
                if r not in found and r not in queue:
                    queue.append(r)
            if sink and len(batch) >= 20:
                sink(batch); done += len(batch); batch = []
                log.info("telethon bootstrap: записано %d, найдено %d, очередь %d", done, len(found), len(queue))
            await asyncio.sleep(0.25)
        if sink and batch:
            sink(batch); done += len(batch)
        return done if sink else len(found)
    finally:
        await client.disconnect()


async def _enrich(usernames: list[str]) -> list[dict]:
    client = _make_client()
    if client is None:
        return []
    await client.connect()
    try:
        if not await client.is_user_authorized():
            return []
        out = []
        for u in usernames:
            out.append(await _metrics(client, u))
            await asyncio.sleep(0.25)
        return out
    finally:
        await client.disconnect()


def discover_telethon(seeds: list[str] | None = None, max_channels: int = 400, dry_run: bool = False) -> int:
    """Развернуть афиша-граф через рекомендации Telegram + снять метрики (инкрементальная запись).
    seeds=None → афиша-таргеты. Возвращает число записанных каналов."""
    settings = get_settings()
    if not dry_run and not settings.adstat_enabled:
        log.info("adstat telethon: ADSTAT_ENABLED=false — пропуск")
        return 0
    seeds = seeds or _afisha_seeds()
    if not seeds:
        log.warning("adstat telethon: нет сидов")
        return 0

    def sink(batch: list[dict]) -> None:
        upsert_targets([{"username": r["username"], "city": None} for r in batch])
        persist_snapshots(batch)

    n = asyncio.run(_crawl(seeds, max_channels, sink=None if dry_run else sink))
    log.info("adstat telethon discover: %d каналов (из %d сидов, max=%d)", n, len(seeds), max_channels)
    return n


def enrich_telethon(usernames: list[str], dry_run: bool = False) -> list[dict]:
    """Снять Telethon-метрики по списку каналов (для обогащения уже найденных)."""
    rows = asyncio.run(_enrich([u.lstrip("@") for u in usernames]))
    if not dry_run:
        persist_snapshots([r for r in rows if not r.get("error")])
    return rows
