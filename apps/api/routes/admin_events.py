"""Admin-панель: вкладка «События» — поиск/модерация каталога (events.events).

Админ видит ВСЕ статусы (включая hidden — публичный API отдаёт только active). Действия: скрыть/вернуть
(status), реклассификация (category). Поиск по названию (trgm-индекс) + фильтры статус/категория,
серверная пагинация (каталог ~20k). Все ручки под require_admin, SQL через text() c bind-параметрами.
"""
import re

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.services.admin_auth import require_admin, write_audit
from core.db.session import get_async_db
from core.domain.codes import event_code

router = APIRouter(prefix="/v1/admin", tags=["admin"])

_UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
_PAGE_SIZE = 100


@router.get("/events/facets")
async def event_facets(actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db)) -> dict:
    """Списки для фильтров: распознанные категории и статусы (реальные значения из БД)."""
    cats = (await db.execute(text("SELECT DISTINCT category FROM events.events WHERE category <> '' ORDER BY category"))).scalars().all()
    stats = (await db.execute(text("SELECT DISTINCT status FROM events.events ORDER BY status"))).scalars().all()
    return {"categories": list(cats), "statuses": list(stats)}


@router.get("/events")
async def list_events(
    q: str | None = None,
    status: str | None = None,
    category: str | None = None,
    page: int = 0,
    actor: str = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """Поиск событий (вкл. hidden). q → ILIKE по названию (trgm). Фильтры status/category. Пагинация по 100."""
    offset = max(0, int(page)) * _PAGE_SIZE
    params = {
        "q": q,
        "like": f"%{q}%" if q else None,
        "status": status,
        "category": category,
        "limit": _PAGE_SIZE,
        "offset": offset,
    }
    # CAST на IS NULL-параметрах (psycopg AmbiguousParameter на untyped-NULL).
    where = (
        "(CAST(:q AS text) IS NULL OR e.canonical_title ILIKE :like) "
        "AND (CAST(:status AS text) IS NULL OR e.status = :status) "
        "AND (CAST(:category AS text) IS NULL OR e.category = :category)"
    )
    total = (await db.execute(text(f"SELECT count(*) FROM events.events e WHERE {where}"), params)).scalar()
    rows = (await db.execute(text(
        "SELECT e.event_id, e.display_no, e.canonical_title, e.category, e.subcategory, e.status, "
        "  (e.cached_image_url IS NOT NULL OR e.primary_image_url <> '') AS has_image, e.created_at, "
        "  o.date_start, v.city "
        "FROM events.events e "
        "LEFT JOIN LATERAL ("
        "  SELECT date_start, venue_id FROM events.event_occurrences oo "
        "  WHERE oo.event_id = e.event_id ORDER BY (oo.date_start < now()) ASC, oo.date_start ASC LIMIT 1"
        ") o ON true "
        "LEFT JOIN events.venues v ON v.venue_id = o.venue_id "
        f"WHERE {where} ORDER BY e.created_at DESC LIMIT :limit OFFSET :offset"
    ), params)).all()
    items = []
    for r in rows:
        items.append({
            "event_id": str(r[0]),
            "display_no": r[1],
            "code": event_code(r[1], r[9]) if r[1] else None,
            "title": r[2],
            "category": r[3],
            "subcategory": r[4],
            "status": r[5],
            "has_image": bool(r[6]),
            "created_at": r[7].isoformat() if r[7] else None,
            "next_date": r[8].isoformat() if r[8] else None,
            "city": r[9],
        })
    return {"items": items, "total": int(total or 0), "page": int(page), "page_size": _PAGE_SIZE}


@router.post("/events/{event_id}")
async def update_event(
    event_id: str,
    request: Request,
    payload: dict = Body(...),
    actor: str = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """Обновить событие: status ('active'/'hidden') и/или category. Скрытое (hidden) выпадает из публичного
    API (фильтр =active), но остаётся в каталоге и обратимо."""
    if not _UUID_RE.match(event_id):
        raise HTTPException(status_code=400, detail="bad event id")
    sets, params = [], {"id": event_id}
    new_status = payload.get("status")
    if new_status is not None:
        if new_status not in ("active", "hidden"):
            raise HTTPException(status_code=400, detail="status: active | hidden")
        sets.append("status = :status")
        params["status"] = new_status
    new_cat = payload.get("category")
    if isinstance(new_cat, str) and new_cat.strip():
        sets.append("category = :cat")
        params["cat"] = new_cat.strip()
    if not sets:
        raise HTTPException(status_code=400, detail="нечего менять (status и/или category)")
    res = await db.execute(
        text(f"UPDATE events.events SET {', '.join(sets)} WHERE event_id = CAST(:id AS uuid)"), params
    )
    if not res.rowcount:
        raise HTTPException(status_code=404, detail="событие не найдено")
    await db.commit()
    await write_audit(
        db, request, actor, "event.update", target=event_id,
        params={k: params[k] for k in params if k != "id"}, result="ok",
    )
    return {"ok": True}
