"""Admin-панель: вкладка «Города» — реестр активных городов (из кода active_cities) + живые счётчики.

Города задаются в коде (не в БД), здесь — read-only обзор: таймзона (фикс. UTC-offset), число площадок/
событий/пользователей и какие источники покрывают город. require_admin.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.services.admin_auth import require_admin
from core.db.session import get_async_db
from core.domain.cities import active_cities

router = APIRouter(prefix="/v1/admin", tags=["admin"])


@router.get("/cities")
async def list_cities(actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db)) -> dict:
    venues = {r[0]: int(r[1]) for r in (await db.execute(text(
        "SELECT city, count(*) FROM events.venues WHERE city <> '' GROUP BY city"))).all()}
    users = {r[0]: int(r[1]) for r in (await db.execute(text(
        "SELECT city_slug, count(*) FROM ref.users WHERE city_slug IS NOT NULL AND city_slug <> '' GROUP BY city_slug"))).all()}
    evs = {r[0]: int(r[1]) for r in (await db.execute(text(
        "SELECT v.city, count(DISTINCT e.event_id) FROM events.events e "
        "JOIN events.event_occurrences o ON o.event_id = e.event_id "
        "JOIN events.venues v ON v.venue_id = o.venue_id "
        "WHERE e.status = 'active' AND v.city <> '' GROUP BY v.city"))).all()}

    items = []
    for c in active_cities():
        srcs = [name for name, on in (
            ("yandex", bool(c.yandex_city)), ("kudago", bool(c.kudago_location)), ("afisha", bool(c.afisha_city))
        ) if on]
        items.append({
            "slug": c.slug, "name": c.name, "tz": c.timezone, "utc_offset": c.utc_offset_hours,
            "venues": venues.get(c.name, 0), "events": evs.get(c.name, 0), "users": users.get(c.slug, 0),
            "sources": srcs, "has_telegram": c.city_id is not None,
        })
    return {"items": items}
