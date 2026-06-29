"""Admin-панель: вкладка «Источники» — таблица источников ингеста (ref.sources) + тоглы.

~376 источников (323 telegram + 53 web), поэтому список ВСЕГДА с фильтрами (q/kind/active) и LIMIT 300.
Последний прогон каждого источника берём через LEFT JOIN LATERAL по events.source_runs.
Все ручки под require_admin (404 если админ не сконфигурён/нет сессии — поверхность невидима).
"""
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.services.admin_auth import require_admin, write_audit
from core.db.session import get_async_db

router = APIRouter(prefix="/v1/admin", tags=["admin"])


@router.get("/sources")
async def list_sources(
    q: str | None = None,
    kind: str | None = None,
    active: bool | None = None,
    actor: str = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """Список источников ингеста. Фильтры: q (ILIKE по name), kind (telegram/web), active (true/false).
    Поля по строке: source_id, name, kind, is_active, crawl_interval_sec, last_status, last_finished.
    ORDER BY name, LIMIT 300. total — полное число строк под текущими фильтрами (для подзаголовка)."""
    params = {
        "q": q,
        "like": f"%{q}%" if q else None,
        "kind": kind,
        "active": active,
    }
    where = (
        "(:q IS NULL OR s.name ILIKE :like) "
        "AND (:kind IS NULL OR s.kind = :kind) "
        "AND (:active IS NULL OR s.is_active = :active)"
    )

    total = (await db.execute(
        text(f"SELECT count(*) FROM ref.sources s WHERE {where}"), params
    )).scalar()

    rows = (await db.execute(
        text(
            "SELECT s.source_id, s.name, s.kind, s.is_active, s.crawl_interval_sec, "
            "  r.status AS last_status, r.finished_at AS last_finished "
            "FROM ref.sources s "
            "LEFT JOIN LATERAL ("
            "  SELECT status, finished_at FROM events.source_runs sr "
            "  WHERE sr.source_id = s.source_id ORDER BY sr.started_at DESC LIMIT 1"
            ") r ON true "
            f"WHERE {where} "
            "ORDER BY s.name LIMIT 300"
        ),
        params,
    )).all()

    items = [
        {
            "source_id": row[0],
            "name": row[1],
            "kind": row[2],
            "is_active": bool(row[3]),
            "crawl_interval_sec": int(row[4]),
            "last_status": row[5],
            "last_finished": row[6].isoformat() if row[6] else None,
        }
        for row in rows
    ]
    return {"items": items, "total": int(total or 0), "shown": len(items)}


@router.post("/sources/{source_id}/toggle")
async def toggle_source(
    source_id: int,
    request: Request,
    payload: dict = Body(...),
    actor: str = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """Вкл/выкл источник: set ref.sources.is_active. ВНИМАНИЕ: фетч-флоу пока НЕ читает этот флаг
    (см. shared_changes_needed) — выключение даст эффект только после подключения проверки в fetch.py."""
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
    """Задать crawl_interval_sec источника. Валидация: целое >= 60 (короче минуты не имеет смысла)."""
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
