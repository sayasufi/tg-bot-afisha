"""Admin-панель: вкладка «Источники» — ref.sources + тоглы.

Отдаём ВСЕ источники разом (~376) с производными полями family (telegram_public/afisha_ru/yandex_afisha/
kudago/timepad) и city (из суффикса имени + реестра городов) — фильтрация/сортировка на клиенте.
Все ручки под require_admin. crawl_interval_sec информативен (реальное расписание — Prefect _SCHEDULE).
"""
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.services.admin_auth import require_admin, write_audit
from core.db.session import get_async_db
from core.domain.cities import DEFAULT_CITY, active_cities

router = APIRouter(prefix="/v1/admin", tags=["admin"])

# slug → отображаемое имя города (in-code реестр, не БД).
_CITY_NAME = {c.slug: c.name for c in active_cities()}


def _family(name: str) -> str:
    """Семейство источника = префикс имени до первого ':' или '-' (имена семейств без дефисов)."""
    return name.split(":", 1)[0].split("-", 1)[0]


def _city_slug(name: str) -> str | None:
    """Город из имени источника. telegram_public:<канал> → None (город per-channel, не в имени).
    web per-city: <family>-<slug> → slug. Голое имя (<family>) → город по умолчанию."""
    if ":" in name:
        return None
    if "-" in name:
        return name.split("-", 1)[1]
    return DEFAULT_CITY.slug


@router.get("/sources")
async def list_sources(actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db)) -> dict:
    rows = (await db.execute(text(
        "SELECT s.source_id, s.name, s.kind, s.is_active, s.crawl_interval_sec, r.status, r.finished_at "
        "FROM ref.sources s "
        "LEFT JOIN LATERAL ("
        "  SELECT status, finished_at FROM events.source_runs sr "
        "  WHERE sr.source_id = s.source_id ORDER BY sr.started_at DESC LIMIT 1"
        ") r ON true ORDER BY s.name LIMIT 500"
    ))).all()
    items = []
    for r in rows:
        name = r[1]
        cslug = _city_slug(name)
        items.append({
            "source_id": r[0],
            "name": name,
            "kind": r[2],
            "family": _family(name),
            "city_slug": cslug,
            "city": _CITY_NAME.get(cslug) if cslug else None,
            "is_active": bool(r[3]),
            "crawl_interval_sec": int(r[4]),
            "last_status": r[5],
            "last_finished": r[6].isoformat() if r[6] else None,
        })
    return {"items": items, "total": len(items)}


@router.post("/sources/{source_id}/toggle")
async def toggle_source(
    source_id: int,
    request: Request,
    payload: dict = Body(...),
    actor: str = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """Вкл/выкл источник (ref.sources.is_active). Подключено к фетчу (apps/worker/tasks/fetch.py:_per_city)."""
    active = bool(payload.get("active"))
    res = await db.execute(
        text("UPDATE ref.sources SET is_active = :a WHERE source_id = :id"),
        {"a": active, "id": source_id},
    )
    if res.rowcount == 0:
        raise HTTPException(status_code=404, detail="источник не найден")
    await db.commit()
    await write_audit(db, request, actor, "source.toggle", target=str(source_id), params={"active": active}, result="ok")
    return {"ok": True, "is_active": active}


@router.post("/sources/{source_id}/interval")
async def set_source_interval(
    source_id: int,
    request: Request,
    payload: dict = Body(...),
    actor: str = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    try:
        sec = int(payload.get("sec"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="sec должен быть целым числом")
    if sec < 60:
        raise HTTPException(status_code=400, detail="интервал не меньше 60 секунд")
    res = await db.execute(
        text("UPDATE ref.sources SET crawl_interval_sec = :s WHERE source_id = :id"),
        {"s": sec, "id": source_id},
    )
    if res.rowcount == 0:
        raise HTTPException(status_code=404, detail="источник не найден")
    await db.commit()
    await write_audit(db, request, actor, "source.interval", target=str(source_id), params={"sec": sec}, result="ok")
    return {"ok": True, "crawl_interval_sec": sec}
