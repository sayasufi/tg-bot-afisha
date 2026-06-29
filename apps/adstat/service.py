"""Оркестратор: читает adstat.targets → скрапит включёнными источниками → пишет в adstat.

Синхронный (curl_cffi синхронный); из Prefect-флоу вызывается через asyncio.to_thread.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.config.settings import get_settings
from apps.adstat.models import AdChannel, AdSnapshot, AdTarget
from core.db.session import SessionLocal

from apps.adstat.telemetr import TelemetrClient
from apps.adstat.tgstat import TGStatClient

log = logging.getLogger(__name__)


def _build_clients(settings, sources: list[str] | None = None) -> list:
    """sources=None → все включённые источники; иначе фильтр (напр. ['telemetr'] для лёгкого daily)."""
    clients = []
    if settings.adstat_telemetr_enabled and (sources is None or "telemetr" in sources):
        c = TelemetrClient(settings.adstat_cookies_path)
        if c.ready:
            clients.append(c)
        else:
            log.warning("adstat: Telemetr enabled but no session cookie at %s", settings.adstat_cookies_path)
    if settings.adstat_tgstat_enabled and (sources is None or "tgstat" in sources):
        c = TGStatClient(settings.adstat_cookies_path, settings.adstat_flaresolverr_url)
        if c.ready:
            clients.append(c)
        else:
            log.warning("adstat: TGStat enabled but no session cookie at %s", settings.adstat_cookies_path)
    return clients


def _active_targets(limit: int | None = None, stale_first: bool = False) -> list[str]:
    """Активные таргеты. stale_first → сортировка по AdChannel.last_scraped_at (NULL=никогда → первыми):
    дневной флоу берёт срез самых несвежих, охват ротируется по дням (вместо «все ~6000 за раз» → таймаут)."""
    with SessionLocal() as db:
        stmt = select(AdTarget.username).where(AdTarget.is_active.is_(True))
        if stale_first:
            stmt = stmt.order_by(AdTarget.last_scraped_at.asc().nulls_first(), AdTarget.target_id)
        if limit:
            stmt = stmt.limit(limit)
        rows = db.execute(stmt).scalars().all()
    return [u for u in rows]


def scrape(usernames: list[str] | None = None, dry_run: bool = False,
           sources: list[str] | None = None, limit: int | None = None) -> list[dict]:
    """Скрапит каналы (или активные targets) и пишет снимки. dry_run → не трогает БД, вернёт результаты.
    sources=['telemetr'] ограничивает источники (для лёгкого ежедневного флоу).
    limit → не более N таргетов за прогон, самые несвежие первыми (ротация охвата; защита от таймаута)."""
    settings = get_settings()
    if not dry_run and not settings.adstat_enabled:
        log.info("adstat: ADSTAT_ENABLED=false — пропуск")
        return []

    clients = _build_clients(settings, sources)
    if not clients:
        log.warning("adstat: нет готовых источников (куки?) — пропуск")
        return []

    names = usernames if usernames else _active_targets(limit=limit, stale_first=bool(limit))
    if not names:
        log.info("adstat: список каналов пуст (нет targets)")
        return []

    results: list[dict] = []
    for u in names:
        for client in clients:
            try:
                d = client.fetch(u)
            except Exception as e:  # noqa: BLE001
                d = {"source": getattr(client, "SOURCE", "?"), "username": u.lstrip("@"), "error": str(e)[:200]}
            if d:
                results.append(d)
            time.sleep(settings.adstat_delay_sec)

    ok = [r for r in results if not r.get("error")]
    errs = [r for r in results if r.get("error")]
    for r in errs:
        log.warning("adstat scrape error %s/%s: %s", r.get("source"), r.get("username"), r.get("error"))

    if not dry_run:
        persist_snapshots(ok)
        # Отметить ВСЕ опрошенные таргеты (вкл. not_found) как недавно-опрошенные → ротация не клинит на junk.
        norm = list({u.lstrip("@").lower() for u in names})
        if norm:
            with SessionLocal() as db:
                db.execute(update(AdTarget).where(AdTarget.username.in_(norm)).values(last_scraped_at=datetime.now(timezone.utc)))
                db.commit()
    log.info("adstat: %d каналов, %d снимков ok, %d ошибок", len(names), len(ok), len(errs))
    return results


def upsert_targets(targets: list[dict]) -> int:
    """Добавить/обновить каналы в adstat.targets (username + city hint). Идемпотентно."""
    if not targets:
        return 0
    n = 0
    with SessionLocal() as db:
        for t in targets:
            u = (t.get("username") or "").lstrip("@").lower()
            if not u:
                continue
            ins = pg_insert(AdTarget).values(username=u, city=t.get("city"))
            db.execute(ins.on_conflict_do_update(
                index_elements=[AdTarget.username],
                set_={"city": func.coalesce(ins.excluded.city, AdTarget.city)},
            ))
            n += 1
        db.commit()
    return n


def persist_snapshots(rows: list[dict]) -> None:
    if not rows:
        return
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        for d in rows:
            uname = (d.get("username") or "").lstrip("@").lower()
            if not uname:
                continue
            ad_price = d.get("ad_price")
            if ad_price is None and d.get("post_price"):
                ad_price = int(d["post_price"])
            ins = pg_insert(AdChannel).values(
                username=uname, peer_id=d.get("peer_id"), title=d.get("title"),
                language=d.get("language"), is_verified=d.get("is_verified"),
                ad_price=ad_price, last_scraped_at=now,
            )
            # COALESCE(excluded, existing): новый источник без поля не затирает уже известное.
            stmt = ins.on_conflict_do_update(
                index_elements=[AdChannel.username],
                set_={
                    "peer_id": func.coalesce(ins.excluded.peer_id, AdChannel.peer_id),
                    "title": func.coalesce(ins.excluded.title, AdChannel.title),
                    "language": func.coalesce(ins.excluded.language, AdChannel.language),
                    "is_verified": func.coalesce(ins.excluded.is_verified, AdChannel.is_verified),
                    "ad_price": func.coalesce(ins.excluded.ad_price, AdChannel.ad_price),
                    "last_scraped_at": now,
                    "updated_at": now,
                },
            ).returning(AdChannel.channel_id)
            channel_id = db.execute(stmt).scalar_one()

            db.add(AdSnapshot(
                channel_id=channel_id, source=d["source"], captured_at=now,
                subscribers=d.get("subscribers"), er=d.get("er"), err=d.get("err"),
                post_price=d.get("post_price"), cpm=d.get("cpm"), rating=d.get("rating"),
                avg_reach=d.get("avg_reach"), quality_score=d.get("quality_score"),
                premium_subs=d.get("premium_subs"), month_growth=d.get("month_growth"),
                mentions=d.get("mentions"), is_scam=d.get("is_scam"), is_boosting=d.get("is_boosting"),
                is_stolen=d.get("is_stolen"), sanctioned=d.get("sanctioned"), raw=d.get("raw"),
            ))
        db.commit()
