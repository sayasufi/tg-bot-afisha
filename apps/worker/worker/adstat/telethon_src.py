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


def _make_client_from(acc: dict):
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    s = get_settings()
    return TelegramClient(
        StringSession(acc["session"]),
        acc.get("api_id") or s.telethon_api_id,
        acc.get("api_hash") or s.telethon_api_hash,
    )


def _load_pool() -> list[dict]:
    """Активные аккаунты пула (flood_until в прошлом/пусто). Пусто → фолбэк на .env-сессию."""
    from datetime import datetime, timezone

    from sqlalchemy import select

    from core.db.models.adstat import AdTgAccount
    from core.db.session import SessionLocal

    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        accs = db.execute(select(AdTgAccount).where(AdTgAccount.is_active.is_(True))).scalars().all()
        return [
            {"account_id": a.account_id, "label": a.label, "api_id": a.api_id,
             "api_hash": a.api_hash, "session": a.session}
            for a in accs if (a.flood_until is None or a.flood_until <= now)
        ]


async def _connect_clients() -> list:
    """Построить и подключить авторизованных клиентов пула. Возвращает пары (account|None, client)."""
    pool = _load_pool()
    if pool:
        cands = [(a, _make_client_from(a)) for a in pool]
    else:
        # _load_pool пуст: либо все отдыхают (FloodWait), либо таблица без активных аккаунтов.
        from sqlalchemy import func as sqlfunc
        from sqlalchemy import select

        from core.db.models.adstat import AdTgAccount
        from core.db.session import SessionLocal

        with SessionLocal() as db:
            active_total = db.execute(
                select(sqlfunc.count()).select_from(AdTgAccount).where(AdTgAccount.is_active.is_(True))
            ).scalar() or 0
        if active_total:  # аккаунты есть, но все отдыхают — .env (это один из них) не трогаем
            log.info("telethon: все аккаунты пула отдыхают (FloodWait) — пропуск")
            cands = []
        else:  # пул пуст → фолбэк на .env-сессию
            cands = [(None, _make_client())] if _make_client() else []
    pairs = []
    for acc, c in cands:
        if c is None:
            continue
        try:
            await c.connect()
            if await c.is_user_authorized():
                pairs.append((acc, c))
            else:
                log.warning("telethon pool: %s не авторизован — пропуск", (acc or {}).get("label", "env"))
                await c.disconnect()
        except Exception as e:  # noqa: BLE001
            log.warning("telethon pool connect: %s", e)
    return pairs


def _mark_flood(account_id: int, seconds: int) -> None:
    """Пометить аккаунт отдыхающим до окончания FloodWait — пул его пропустит."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import update

    from core.db.models.adstat import AdTgAccount
    from core.db.session import SessionLocal

    until = datetime.now(timezone.utc) + timedelta(seconds=min(seconds + 60, 86400))
    with SessionLocal() as db:
        db.execute(update(AdTgAccount).where(AdTgAccount.account_id == account_id).values(flood_until=until))
        db.commit()


async def _metrics_ent(client, entity) -> dict | None:
    """Метрики по ГОТОВОМУ entity (Channel с access_hash) — без ResolveUsername."""
    from telethon.errors import FloodWaitError
    from telethon.tl.functions.channels import GetFullChannelRequest

    u = getattr(entity, "username", None)
    if not u:
        return None  # пропускаем каналы без публичного username
    try:
        full = await client(GetFullChannelRequest(entity))
        subs = getattr(full.full_chat, "participants_count", None)
    except FloodWaitError:
        raise
    except Exception:  # noqa: BLE001
        return {"source": "telethon", "username": u, "error": "getfull"}
    views, dates, fwd = [], [], []
    try:
        async for msg in client.iter_messages(entity, limit=20):
            if getattr(msg, "views", None):
                views.append(msg.views)
            if getattr(msg, "forwards", None):
                fwd.append(msg.forwards)
            if msg.date:
                dates.append(msg.date)
    except FloodWaitError:
        raise
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
        "source": "telethon", "username": u, "peer_id": getattr(entity, "id", None),
        "title": getattr(entity, "title", None), "subscribers": subs, "avg_reach": avg_reach, "er": er,
        "raw": {"posts_per_week": freq, "samples": len(views),
                "avg_forwards": int(sum(fwd) / len(fwd)) if fwd else None},
    }


async def _recs_ent(client, entity) -> list:
    """Рекомендации по entity → список Channel-объектов (с access_hash, БЕЗ резолва)."""
    from telethon.errors import FloodWaitError
    from telethon.tl.functions.channels import GetChannelRecommendationsRequest

    try:
        res = await client(GetChannelRecommendationsRequest(channel=entity))
        return list(getattr(res, "chats", []))
    except FloodWaitError:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("telethon recs %s: %s", getattr(entity, "username", "?"), e)
        return []


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


# Опорные сиды-хинты для гарантированного покрытия (Москва / Питер / общие по России).
# Невалидные просто отвалятся на резолве (catch) — безвредно.
_SEED_HINTS = [
    # Москва
    "mscculture", "mosafishka", "moscowes", "kyda_moscow", "i_moskva", "kudamoscow",
    # Питер
    "afishapitera", "kudagospb", "spb_gid", "kudaspb", "peterburg2", "fiesta_spb",
    # Общие по России / мульти-город
    "kudago", "afisha", "theatrehd", "kassirru", "gorbilet",
]


def _afisha_seeds(limit: int = 150) -> list[str]:
    """Сиды = опорные хинты (Москва/Питер/Россия) + СЛУЧАЙНАЯ подвыборка из ВСЕХ найденных каналов
    (telemetr / telethon / **telega** — включая ~5400 telega-каналов). Рандом КАЖДЫЙ прогон → каждый день
    другой район графа рекомендаций, поэтому крауль расширяется за плато (раньше брал один и тот же ~120-набор
    БЕЗ рандома → один и тот же neighborhood → упор в 445). Резолвится только сидами (~150) → флуд-безопасно;
    найденные идут по access_hash."""
    from sqlalchemy import func, select

    from core.db.models.adstat import AdChannel, AdSnapshot
    from core.db.session import SessionLocal

    seeds = list(dict.fromkeys(_SEED_HINTS))
    with SessionLocal() as db:
        # DISTINCT в подзапросе, СНАРУЖИ ORDER BY random() (Postgres запрещает ORDER BY random() вместе с DISTINCT).
        sub = (
            select(AdChannel.username)
            .join(AdSnapshot, AdSnapshot.channel_id == AdChannel.channel_id)
            .where(AdChannel.username.is_not(None))
            .where(AdSnapshot.source.in_(["telemetr", "telethon", "telega"]))
            .distinct()
            .subquery()
        )
        rows = db.execute(select(sub.c.username).order_by(func.random()).limit(limit)).scalars().all()
    for u in rows:
        if u not in seeds:
            seeds.append(u)
    return seeds


async def _crawl(seeds: list[str], max_channels: int, sink=None) -> int:
    """Параллельный BFS по рекомендациям через ПУЛ. ResolveUsername — ТОЛЬКО для сидов; найденные
    каналы идут по access_hash (Channel-объекты из рекомендаций) → почти нет FloodWait.
    FloodWait у аккаунта → помечаем flood_until и выводим его клиента, остальные продолжают."""
    from telethon.errors import FloodWaitError

    pairs = await _connect_clients()
    if not pairs:
        log.warning("telethon: нет авторизованных клиентов — пропуск")
        return 0
    log.info("telethon: клиентов в пуле — %d", len(pairs))

    found_ids: set[int] = set()
    queue: list = []  # Channel entities (с access_hash)
    batch: list[dict] = []
    processed = 0
    done = 0
    lock = asyncio.Lock()

    def _enqueue(ent) -> None:
        i = getattr(ent, "id", None)
        if i and i not in found_ids and getattr(ent, "username", None):
            found_ids.add(i)
            queue.append(ent)

    # Сиды резолвим один раз (единственный ResolveUsername), распределяя по клиентам.
    for idx, u in enumerate(dict.fromkeys(s.lstrip("@") for s in seeds)):
        _, c = pairs[idx % len(pairs)]
        try:
            _enqueue(await c.get_entity(u))
        except Exception as e:  # noqa: BLE001
            log.warning("seed resolve %s: %s", u, e)
        await asyncio.sleep(0.3)

    async def take():
        async with lock:
            if processed >= max_channels or not queue:
                return None
            return queue.pop(0)

    async def push(m, recs):
        nonlocal processed, done, batch
        flush = None
        async with lock:
            processed += 1
            if m and not m.get("error"):
                batch.append(m)
            for r in recs:
                _enqueue(r)
            if sink and len(batch) >= 20:
                flush, batch = batch, []
        if flush:
            sink(flush)
            async with lock:
                done += len(flush)
                log.info("telethon: записано %d, найдено %d, очередь %d", done, len(found_ids), len(queue))

    async def worker(account, client):
        idle = 0
        while True:
            ent = await take()
            if ent is None:
                idle += 1
                if idle >= 3:
                    return
                await asyncio.sleep(1.0)
                continue
            idle = 0
            try:
                m = await _metrics_ent(client, ent)
                recs = await _recs_ent(client, ent)
            except FloodWaitError as e:
                log.warning("telethon FloodWait %ss — аккаунт %s отдыхает", e.seconds, (account or {}).get("label", "env"))
                if account:
                    _mark_flood(account["account_id"], e.seconds)
                return  # клиент выбывает, остальные продолжают
            await push(m, recs)
            await asyncio.sleep(0.3)

    try:
        await asyncio.gather(*[worker(a, c) for a, c in pairs])
        if sink and batch:
            sink(batch); done += len(batch)
        return done if sink else processed
    finally:
        for _, c in pairs:
            try:
                await c.disconnect()
            except Exception:  # noqa: BLE001
                pass


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
