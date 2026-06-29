"""Admin-панель: вкладка «Пользователи» — каталог ref.users (read-only).

Поиск (username/имя), фильтры: город, онбординг, подписка на дайджест. Серверная сортировка по всему
набору + пагинация 100. Доп-колонки: число избранного, число друзей (accepted), кол-во интересов,
последняя активность. Город — slug→имя через active_cities(). require_admin.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.services.admin_auth import require_admin
from core.domain.cities import active_cities
from core.db.session import get_async_db

router = APIRouter(prefix="/v1/admin", tags=["admin"])
_PAGE_SIZE = 100
_CITY_NAME = {c.slug: c.name for c in active_cities()}

_SORT = {
    "username": "u.username",
    "city": "u.city_slug",
    "created": "u.created_at",
    "active": "u.last_active_at",
    "favorites": "fav_count",
    "friends": "friend_count",
}


@router.get("/users/facets")
async def user_facets(actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db)) -> dict:
    slugs = (await db.execute(text(
        "SELECT DISTINCT city_slug FROM ref.users WHERE city_slug IS NOT NULL AND city_slug <> '' ORDER BY city_slug"
    ))).scalars().all()
    return {"cities": [{"slug": s, "name": _CITY_NAME.get(s, s)} for s in slugs]}


@router.get("/users")
async def list_users(
    q: str | None = None,
    city: str | None = None,
    onboarded: str | None = None,  # "true" | "false"
    digest: str | None = None,     # "true" | "false"
    sort: str | None = None,
    dir: str | None = None,
    page: int = 0,
    actor: str = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    offset = max(0, int(page)) * _PAGE_SIZE
    params: dict = {"q": q, "like": f"%{q}%" if q else None, "limit": _PAGE_SIZE, "offset": offset}
    conds = ["(CAST(:q AS text) IS NULL OR u.username ILIKE :like OR u.first_name ILIKE :like)"]
    if city:
        conds.append("u.city_slug = :city")
        params["city"] = city
    if onboarded in ("true", "false"):
        conds.append("u.onboarded = :onb")
        params["onb"] = onboarded == "true"
    if digest in ("true", "false"):
        conds.append("u.notify_digest = :dig")
        params["dig"] = digest == "true"
    where = " AND ".join(conds)
    total = (await db.execute(text(f"SELECT count(*) FROM ref.users u WHERE {where}"), params)).scalar()

    sort_col = _SORT.get(sort or "", "u.last_active_at")
    direction = "DESC" if (dir or "desc").lower() == "desc" else "ASC"
    rows = (await db.execute(text(
        "SELECT u.telegram_user_id, u.username, u.first_name, u.city_slug, u.onboarded, "
        "  u.notify_digest, u.notify_reminders, COALESCE(array_length(u.interests, 1), 0) AS n_interests, "
        "  (SELECT count(*) FROM ref.user_favorites f WHERE f.telegram_user_id = u.telegram_user_id) AS fav_count, "
        "  (SELECT count(*) FROM ref.user_friends fr WHERE fr.user_id = u.telegram_user_id AND fr.status = 'accepted') AS friend_count, "
        "  u.created_at, u.last_active_at "
        "FROM ref.users u "
        f"WHERE {where} ORDER BY {sort_col} {direction} NULLS LAST, u.telegram_user_id LIMIT :limit OFFSET :offset"
    ), params)).all()
    items = [{
        "telegram_user_id": r[0],
        "username": r[1],
        "first_name": r[2],
        "city": _CITY_NAME.get(r[3], r[3]) if r[3] else None,
        "onboarded": bool(r[4]),
        "notify_digest": bool(r[5]),
        "notify_reminders": bool(r[6]),
        "n_interests": int(r[7] or 0),
        "fav_count": int(r[8] or 0),
        "friend_count": int(r[9] or 0),
        "created_at": r[10].isoformat() if r[10] else None,
        "last_active_at": r[11].isoformat() if r[11] else None,
    } for r in rows]
    return {"items": items, "total": int(total or 0), "page": int(page), "page_size": _PAGE_SIZE}
