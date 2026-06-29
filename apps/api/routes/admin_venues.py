"""Admin-панель: вкладка «Площадки» — каталог venues (events.venues).

Read-only модерация: поиск (имя/адрес), фильтр по городу и «проблеме» (без координат / без часов),
серверная сортировка по ВСЕМУ набору, пагинация 100. Доп-колонки: число активных событий (через
occurrences), наличие координат (geom), наличие часов (hours_json не NULL и не пустой {}), провайдер
геокода + уверенность.

Точечные фиксы (перегеокод / часы) запускаются батч-прогонами Prefect-деплойментов
(correct-venue-coords / resolve-venue-hours): они идут по limit, а не по одной площадке, поэтому
выведены кнопкой-прогоном на странице, а не действием на строку. require_admin.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.services.admin_auth import require_admin
from core.db.session import get_async_db

router = APIRouter(prefix="/v1/admin", tags=["admin"])
_PAGE_SIZE = 100

# Whitelist колонок сортировки (никаких сырых значений в ORDER BY — защита от инъекции).
_SORT = {
    "name": "v.name",
    "city": "v.city",
    "events": "n_events",  # алиас из латерального счётчика ниже
    "created": "v.created_at",
}

# Площадка → число активных событий (через occurrences). Латераль, чтобы можно было сортировать по счётчику.
_JOIN = (
    " LEFT JOIN LATERAL ("
    "   SELECT count(DISTINCT e.event_id) AS n_events "
    "   FROM events.event_occurrences o "
    "   JOIN events.events e ON e.event_id = o.event_id AND e.status = 'active' "
    "   WHERE o.venue_id = v.venue_id"
    " ) ec ON true "
)


@router.get("/venues/facets")
async def venue_facets(actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db)) -> dict:
    cities = (await db.execute(text(
        "SELECT DISTINCT city FROM events.venues WHERE city IS NOT NULL AND city <> '' ORDER BY city"
    ))).scalars().all()
    return {"cities": list(cities)}


@router.get("/venues")
async def list_venues(
    q: str | None = None,
    city: str | None = None,
    missing: str | None = None,  # coords | hours — фокус-фильтры модерации
    sort: str | None = None,
    dir: str | None = None,
    page: int = 0,
    actor: str = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """Список площадок. missing: coords (geom IS NULL) | hours (нет или пустые {}). Сортировка серверная."""
    offset = min(max(0, int(page)), 100000) * _PAGE_SIZE
    params: dict = {"q": q, "like": f"%{q}%" if q else None, "limit": _PAGE_SIZE, "offset": offset}
    # CAST(:q AS text) IS NULL — иначе asyncpg не выводит тип bind-параметра при NULL (AmbiguousParameter).
    conds = ["(CAST(:q AS text) IS NULL OR v.name ILIKE :like OR v.address ILIKE :like)"]
    if city:
        conds.append("v.city = :city")
        params["city"] = city
    if missing == "coords":
        conds.append("v.geom IS NULL")
    elif missing == "hours":
        conds.append("(v.hours_json IS NULL OR v.hours_json::text IN ('null', '{}'))")
    where = " AND ".join(conds)
    # Фильтры ссылаются только на v → латераль в count не нужна (быстро).
    total = (await db.execute(text(f"SELECT count(*) FROM events.venues v WHERE {where}"), params)).scalar()

    sort_col = _SORT.get(sort or "", "n_events")
    direction = "DESC" if (dir or "").lower() == "desc" else "ASC"
    rows = (await db.execute(text(
        "SELECT v.venue_id, v.name, v.city, v.address, "
        "  (v.geom IS NOT NULL) AS has_coords, "
        "  (v.hours_json IS NOT NULL AND v.hours_json::text NOT IN ('null', '{}')) AS has_hours, "
        "  v.geocode_provider, round(v.geocode_confidence::numeric, 2) AS geo_conf, "
        "  COALESCE(ec.n_events, 0) AS n_events "
        "FROM events.venues v " + _JOIN +
        f"WHERE {where} ORDER BY {sort_col} {direction} NULLS LAST, v.venue_id LIMIT :limit OFFSET :offset"
    ), params)).all()
    items = [{
        "venue_id": r[0],
        "name": r[1],
        "city": r[2],
        "address": r[3],
        "has_coords": bool(r[4]),
        "has_hours": bool(r[5]),
        "geocode_provider": r[6] or "",
        "geocode_confidence": float(r[7] or 0),
        "n_events": int(r[8]),
    } for r in rows]
    return {"items": items, "total": int(total or 0), "page": int(page), "page_size": _PAGE_SIZE}
