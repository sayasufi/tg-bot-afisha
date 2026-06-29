"""Admin-панель: вкладка «События» — поиск/модерация каталога (events.events).

Админ видит ВСЕ статусы (вкл. hidden). Фильтры: поиск (trgm), статус, категория, ГОРОД, ДАТА. Сортировка
СЕРВЕРНАЯ (ORDER BY по всему набору, не по странице) — пагинация по 100. Действия: скрыть/вернуть, реклассиф.
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

# Whitelist колонок сортировки (никаких сырых значений в ORDER BY — защита от инъекции).
_SORT = {
    "title": "e.canonical_title",
    "category": "e.category",
    "status": "e.status",
    "city": "v.city",
    "date": "o.date_start",
    "created": "e.created_at",
}

# Соединение событие → ближайшая (будущее-first) сессия + площадка. Нужно для города/даты/сортировки по ним.
_JOIN = (
    " LEFT JOIN LATERAL ("
    "   SELECT date_start, venue_id FROM events.event_occurrences oo "
    "   WHERE oo.event_id = e.event_id ORDER BY (oo.date_start < now()) ASC, oo.date_start ASC LIMIT 1"
    " ) o ON true "
    " LEFT JOIN events.venues v ON v.venue_id = o.venue_id "
)


@router.get("/events/facets")
async def event_facets(actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db)) -> dict:
    """Списки для фильтров: категории, статусы (всегда + active/hidden), города (из площадок)."""
    cats = (await db.execute(text("SELECT DISTINCT category FROM events.events WHERE category <> '' ORDER BY category"))).scalars().all()
    stats = set((await db.execute(text("SELECT DISTINCT status FROM events.events"))).scalars().all())
    stats |= {"active", "hidden"}
    cities = (await db.execute(text("SELECT DISTINCT city FROM events.venues WHERE city IS NOT NULL AND city <> '' ORDER BY city"))).scalars().all()
    return {"categories": list(cats), "statuses": sorted(stats), "cities": list(cities)}


@router.get("/events")
async def list_events(
    q: str | None = None,
    status: str | None = None,
    category: str | None = None,
    city: str | None = None,
    date: str | None = None,
    sort: str | None = None,
    dir: str | None = None,
    page: int = 0,
    actor: str = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """Поиск/фильтр событий. date: upcoming|week|past. Сортировка серверная (по всему набору). Пагинация 100."""
    offset = max(0, int(page)) * _PAGE_SIZE
    params: dict = {
        "q": q, "like": f"%{q}%" if q else None,
        "status": status, "category": category, "limit": _PAGE_SIZE, "offset": offset,
    }
    conds = [
        "(CAST(:q AS text) IS NULL OR e.canonical_title ILIKE :like)",
        "(CAST(:status AS text) IS NULL OR e.status = :status)",
        "(CAST(:category AS text) IS NULL OR e.category = :category)",
    ]
    if city:
        conds.append("v.city = :city")
        params["city"] = city
    if date == "upcoming":
        conds.append("o.date_start > now()")
    elif date == "week":
        conds.append("o.date_start >= now() AND o.date_start < now() + interval '7 days'")
    elif date == "past":
        conds.append("(o.date_start <= now() OR o.date_start IS NULL)")
    where = " AND ".join(conds)
    # Город/дата ссылаются на o/v → джойн нужен и в count. Без них count идёт по e (быстро).
    count_join = _JOIN if (city or date) else ""
    total = (await db.execute(text(f"SELECT count(*) FROM events.events e {count_join} WHERE {where}"), params)).scalar()

    sort_col = _SORT.get(sort or "", "e.created_at")
    direction = "DESC" if (dir or "").lower() == "desc" else "ASC"
    rows = (await db.execute(text(
        "SELECT e.event_id, e.display_no, e.canonical_title, e.category, e.subcategory, e.status, "
        "  (e.cached_image_url IS NOT NULL OR e.primary_image_url <> '') AS has_image, e.created_at, "
        "  o.date_start, v.city "
        "FROM events.events e " + _JOIN +
        f"WHERE {where} ORDER BY {sort_col} {direction} NULLS LAST, e.event_id LIMIT :limit OFFSET :offset"
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
    """Обновить событие: status ('active'/'hidden') и/или category. Скрытое выпадает из публичного API (=active)."""
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
