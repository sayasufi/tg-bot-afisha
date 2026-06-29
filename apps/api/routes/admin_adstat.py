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

_CPM_EXPR = "(snap.post_price / NULLIF(rch.avg_reach, 0) * 1000)"
_SORT = {
    "score": "c.score",       # НАШ скор (качество×релевантность на надёжных подписчиках/охвате)
    "subs": "sub.subscribers",
    "reach": "rch.avg_reach",
    "cpm": _CPM_EXPR,
    "price": "snap.post_price",
    "scraped": "c.last_scraped_at",
}

# Подписчики И охват — из НАДЁЖНОГО источника (живое t.me / telethon / telemetr), а не устаревшего
# каталога Telega.in. ER и CPM СЧИТАЕМ из них (охват/подписчики, цена/охват), цену берём из не-tme.
_RANK = "(CASE s.source WHEN 'tme' THEN 4 WHEN 'telethon' THEN 3 WHEN 'telemetr' THEN 2 ELSE 1 END)"
_JOIN = (
    " LEFT JOIN LATERAL ("
    "   SELECT subscribers FROM adstat.snapshots s WHERE s.channel_id = c.channel_id AND s.subscribers IS NOT NULL "
    f"   ORDER BY {_RANK} DESC, s.captured_at DESC LIMIT 1"
    " ) sub ON true "
    " LEFT JOIN LATERAL ("
    "   SELECT avg_reach FROM adstat.snapshots s WHERE s.channel_id = c.channel_id AND s.avg_reach IS NOT NULL "
    f"   ORDER BY {_RANK} DESC, s.captured_at DESC LIMIT 1"
    " ) rch ON true "
    " LEFT JOIN LATERAL ("
    "   SELECT post_price FROM adstat.snapshots s WHERE s.channel_id = c.channel_id "
    "   AND s.source <> 'tme' AND s.post_price IS NOT NULL ORDER BY s.captured_at DESC LIMIT 1"
    " ) snap ON true "
    " LEFT JOIN LATERAL ("
    "   SELECT avg_reactions FROM adstat.snapshots s WHERE s.channel_id = c.channel_id "
    "   AND s.avg_reactions IS NOT NULL ORDER BY s.captured_at DESC LIMIT 1"
    " ) react ON true "
)


@router.get("/adstat/facets")
async def adstat_facets(actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db)) -> dict:
    cities = (await db.execute(text(
        "SELECT DISTINCT city FROM adstat.channels WHERE city IS NOT NULL AND city <> '' ORDER BY city"
    ))).scalars().all()
    relevances = (await db.execute(text(
        "SELECT DISTINCT relevance FROM adstat.channels WHERE relevance IS NOT NULL ORDER BY relevance"
    ))).scalars().all()
    return {"cities": list(cities), "verdicts": ["брать", "осторожно", "мимо"], "relevances": list(relevances)}


@router.get("/adstat")
async def list_channels(
    q: str | None = None, city: str | None = None, min_subs: int | None = None,
    verdict: str | None = None, relevance: str | None = None, has_price: str | None = None,
    sort: str | None = None, dir: str | None = None, page: int = 0,
    actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db),
) -> dict:
    offset = min(max(0, int(page)), 100000) * _PAGE_SIZE
    params: dict = {"q": q, "like": f"%{q}%" if q else None, "limit": _PAGE_SIZE, "offset": offset}
    conds = ["(CAST(:q AS text) IS NULL OR c.username ILIKE :like OR c.title ILIKE :like)"]
    if city:
        conds.append("c.city = :city")
        params["city"] = city
    if verdict:
        conds.append("c.verdict = :verdict")
        params["verdict"] = verdict
    if relevance:
        conds.append("c.relevance = :relevance")
        params["relevance"] = relevance
    if has_price == "1":
        conds.append("c.ad_price > 0")
    need_join = False
    if isinstance(min_subs, int) and min_subs > 0:
        conds.append("sub.subscribers >= :min_subs")
        params["min_subs"] = min_subs
        need_join = True
    where = " AND ".join(conds)
    count_join = _JOIN if need_join else ""
    total = (await db.execute(text(f"SELECT count(*) FROM adstat.channels c {count_join} WHERE {where}"), params)).scalar()

    sort_col = _SORT.get(sort or "", "c.score")
    direction = "DESC" if (dir or "desc").lower() == "desc" else "ASC"
    rows = (await db.execute(text(
        "SELECT c.username, c.title, c.city, c.ad_price, c.last_scraped_at, "
        "  sub.subscribers, rch.avg_reach, "
        "  round(rch.avg_reach::numeric / NULLIF(sub.subscribers, 0) * 100, 1) AS er, "
        f"  snap.post_price, round({_CPM_EXPR}::numeric, 1) AS cpm, c.score, c.verdict, c.quality, c.relevance, "
        "  react.avg_reactions "
        "FROM adstat.channels c " + _JOIN +
        f"WHERE {where} ORDER BY {sort_col} {direction} NULLS LAST, c.channel_id LIMIT :limit OFFSET :offset"
    ), params)).all()
    items = [{
        "username": r[0], "title": r[1], "city": r[2], "ad_price": r[3],
        "last_scraped_at": r[4].isoformat() if r[4] else None,
        "subscribers": r[5], "avg_reach": r[6], "er": float(r[7]) if r[7] is not None else None,
        "post_price": float(r[8]) if r[8] is not None else None,
        "cpm": float(r[9]) if r[9] is not None else None,
        "score": r[10], "verdict": r[11], "quality": r[12], "relevance": r[13], "avg_reactions": r[14],
    } for r in rows]
    return {"items": items, "total": int(total or 0), "page": int(page), "page_size": _PAGE_SIZE}
