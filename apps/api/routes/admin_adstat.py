"""Admin-панель: вкладка «Реклама» — шортлист рекл. TG-каналов (adstat-ресёрч).

Каналы (adstat.channels) + их ПОСЛЕДНИЙ снапшот метрик (adstat.snapshots: подписчики, охват, ER, цена
поста, CPM, рейтинг). Поиск по @username/названию, фильтр по городу и мин. подписчикам, серверная
сортировка (рейтинг/подписчики/охват/CPM/цена) + пагинация 100. require_admin.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.services.admin_auth import require_admin
from core.db.session import get_async_db

router = APIRouter(prefix="/v1/admin", tags=["admin"])
_PAGE_SIZE = 100

_SORT = {
    "rating": "snap.rating",
    "subs": "snap.subscribers",
    "reach": "snap.avg_reach",
    "cpm": "snap.cpm",
    "price": "snap.post_price",
    "scraped": "c.last_scraped_at",
}

_JOIN = (
    " LEFT JOIN LATERAL ("
    "   SELECT subscribers, avg_reach, er, post_price, cpm, rating, captured_at "
    "   FROM adstat.snapshots s WHERE s.channel_id = c.channel_id ORDER BY captured_at DESC LIMIT 1"
    " ) snap ON true "
)


@router.get("/adstat/facets")
async def adstat_facets(actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db)) -> dict:
    cities = (await db.execute(text(
        "SELECT DISTINCT city FROM adstat.channels WHERE city IS NOT NULL AND city <> '' ORDER BY city"
    ))).scalars().all()
    return {"cities": list(cities)}


@router.get("/adstat")
async def list_channels(
    q: str | None = None, city: str | None = None, min_subs: int | None = None,
    sort: str | None = None, dir: str | None = None, page: int = 0,
    actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db),
) -> dict:
    offset = max(0, int(page)) * _PAGE_SIZE
    params: dict = {"q": q, "like": f"%{q}%" if q else None, "limit": _PAGE_SIZE, "offset": offset}
    conds = ["(CAST(:q AS text) IS NULL OR c.username ILIKE :like OR c.title ILIKE :like)"]
    if city:
        conds.append("c.city = :city")
        params["city"] = city
    need_join = False
    if isinstance(min_subs, int) and min_subs > 0:
        conds.append("snap.subscribers >= :min_subs")
        params["min_subs"] = min_subs
        need_join = True
    where = " AND ".join(conds)
    count_join = _JOIN if need_join else ""
    total = (await db.execute(text(f"SELECT count(*) FROM adstat.channels c {count_join} WHERE {where}"), params)).scalar()

    sort_col = _SORT.get(sort or "", "snap.rating")
    direction = "DESC" if (dir or "desc").lower() == "desc" else "ASC"
    rows = (await db.execute(text(
        "SELECT c.username, c.title, c.city, c.ad_price, c.last_scraped_at, "
        "  snap.subscribers, snap.avg_reach, snap.er, snap.post_price, snap.cpm, snap.rating "
        "FROM adstat.channels c " + _JOIN +
        f"WHERE {where} ORDER BY {sort_col} {direction} NULLS LAST, c.channel_id LIMIT :limit OFFSET :offset"
    ), params)).all()
    items = [{
        "username": r[0], "title": r[1], "city": r[2], "ad_price": r[3],
        "last_scraped_at": r[4].isoformat() if r[4] else None,
        "subscribers": r[5], "avg_reach": r[6], "er": float(r[7]) if r[7] is not None else None,
        "post_price": float(r[8]) if r[8] is not None else None,
        "cpm": round(float(r[9]), 1) if r[9] is not None else None,
        "rating": round(float(r[10]), 2) if r[10] is not None else None,
    } for r in rows]
    return {"items": items, "total": int(total or 0), "page": int(page), "page_size": _PAGE_SIZE}
