"""Admin-панель: управление TG-каналами площадок (ref.telegram_channels) — источник telegram-событий.

Список с фильтрами (поиск/город/мёртвые), добавление канала (ON CONFLICT по username → реактивация),
тумблер активности и (пере)привязка venue. Каждая ручка под require_admin (404 если не сконфигурён/нет
сессии — поверхность невидима), все SQL через text() c bind-параметрами, мутации → commit + write_audit.
"""
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.services.admin_auth import require_admin, write_audit
from core.db.session import get_async_db

router = APIRouter(prefix="/v1/admin", tags=["admin"])


def _norm_username(raw: str) -> str:
    """Нормализация хэндла: strip, убрать ведущий @, в нижний регистр."""
    return (raw or "").strip().lstrip("@").strip().lower()


@router.get("/venue-channels")
async def list_venue_channels(
    q: str | None = None,
    city_id: int | None = None,
    dead: bool = False,
    actor: str = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """Каналы площадок с фильтрами. q → username/venue_name ILIKE; city_id → город; dead=true → только неактивные.
    Джойн ref.cities для имени города. LIMIT 200, ORDER BY subscribers DESC NULLS LAST. + total (count)."""
    params = {
        "q": q,
        "like": f"%{q}%" if q else None,
        "city_id": city_id,
        "dead": dead,
    }
    # Касты типов на IS NULL-параметрах: иначе psycopg не выводит тип untyped-NULL → AmbiguousParameter.
    where = (
        " WHERE (:q::text IS NULL OR tc.username ILIKE :like OR tc.venue_name ILIKE :like) "
        " AND (:city_id::int IS NULL OR tc.city_id = :city_id) "
        " AND (NOT :dead::boolean OR tc.is_active = false) "
    )
    total = (await db.execute(
        text("SELECT count(*) FROM ref.telegram_channels tc" + where), params
    )).scalar()
    rows = (await db.execute(text(
        "SELECT tc.channel_id, tc.username, tc.city_id, c.name AS city, tc.is_active, "
        "       tc.venue_name, tc.venue_address, tc.subscribers, tc.updated_at "
        "FROM ref.telegram_channels tc "
        "LEFT JOIN ref.cities c ON c.city_id = tc.city_id"
        + where +
        " ORDER BY tc.subscribers DESC NULLS LAST LIMIT 200"
    ), params)).all()
    return {
        "total": int(total or 0),
        "items": [
            {
                "channel_id": r[0],
                "username": r[1],
                "city_id": r[2],
                "city": r[3],
                "is_active": r[4],
                "venue_name": r[5],
                "venue_address": r[6],
                "subscribers": r[7],
                "updated_at": r[8].isoformat() if r[8] else None,
            }
            for r in rows
        ],
    }


@router.get("/venue-channels/cities")
async def list_channel_cities(
    actor: str = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """Справочник городов для фильтра/формы добавления (только города, где есть каналы — реальный набор)."""
    rows = (await db.execute(text(
        "SELECT c.city_id, c.name, count(tc.channel_id) AS channels "
        "FROM ref.cities c "
        "JOIN ref.telegram_channels tc ON tc.city_id = c.city_id "
        "GROUP BY c.city_id, c.name ORDER BY c.name"
    ))).all()
    return {"items": [{"city_id": r[0], "name": r[1], "channels": int(r[2] or 0)} for r in rows]}


@router.post("/venue-channels")
async def add_venue_channel(
    request: Request,
    payload: dict = Body(...),
    actor: str = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """Добавить/реактивировать канал. username нормализуется; ON CONFLICT (username) → обновить city/venue + is_active=true."""
    username = _norm_username(payload.get("username", ""))
    if not username:
        raise HTTPException(status_code=400, detail="username обязателен")
    city_id = payload.get("city_id")
    if city_id is None:
        raise HTTPException(status_code=400, detail="city_id обязателен")
    try:
        city_id = int(city_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="city_id должен быть числом")
    venue_name = (payload.get("venue_name") or None) or None
    venue_address = (payload.get("venue_address") or None) or None
    if isinstance(venue_name, str):
        venue_name = venue_name.strip() or None
    if isinstance(venue_address, str):
        venue_address = venue_address.strip() or None

    # Case-insensitive upsert: существующие username бывают в смешанном регистре (сид не лоуэркейзил),
    # а ON CONFLICT (username) регистрозависим → искали бы по точному совпадению и создали бы ДУБЛЬ.
    existing = (await db.execute(
        text("SELECT channel_id FROM ref.telegram_channels WHERE LOWER(username) = :u"), {"u": username}
    )).first()
    if existing:
        cid = existing[0]
        await db.execute(text(
            "UPDATE ref.telegram_channels SET city_id = :c, venue_name = :vn, venue_address = :va, "
            "is_active = true WHERE channel_id = :id"
        ), {"c": city_id, "vn": venue_name, "va": venue_address, "id": cid})
    else:
        row = (await db.execute(text(
            "INSERT INTO ref.telegram_channels (username, city_id, is_active, venue_name, venue_address) "
            "VALUES (:u, :c, true, :vn, :va) RETURNING channel_id"
        ), {"u": username, "c": city_id, "vn": venue_name, "va": venue_address})).first()
        cid = row[0] if row else None
    await db.commit()
    await write_audit(
        db, request, actor, "channel.add", target=username,
        params={"channel_id": cid, "city_id": city_id, "venue_name": venue_name, "venue_address": venue_address},
        result="ok",
    )
    return {"ok": True, "channel_id": cid, "username": username}


@router.post("/venue-channels/{channel_id}/toggle")
async def toggle_venue_channel(
    channel_id: int,
    request: Request,
    payload: dict = Body(...),
    actor: str = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """Включить/выключить канал (is_active)."""
    active = bool(payload.get("active"))
    res = await db.execute(
        text("UPDATE ref.telegram_channels SET is_active = :a WHERE channel_id = :id"),
        {"a": active, "id": channel_id},
    )
    if not res.rowcount:
        raise HTTPException(status_code=404, detail="канал не найден")
    await db.commit()
    await write_audit(
        db, request, actor, "channel.toggle", target=str(channel_id),
        params={"active": active}, result="ok",
    )
    return {"ok": True, "is_active": active}


@router.post("/venue-channels/{channel_id}/bind")
async def bind_venue_channel(
    channel_id: int,
    request: Request,
    payload: dict = Body(...),
    actor: str = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """(Пере)привязка площадки к каналу: venue_name/venue_address (+ опц. city_id). Пустые строки → NULL (общий канал)."""
    venue_name = payload.get("venue_name")
    venue_address = payload.get("venue_address")
    if isinstance(venue_name, str):
        venue_name = venue_name.strip() or None
    if isinstance(venue_address, str):
        venue_address = venue_address.strip() or None

    sets = ["venue_name = :vn", "venue_address = :va"]
    params: dict = {"id": channel_id, "vn": venue_name, "va": venue_address}
    city_id = payload.get("city_id")
    if city_id is not None:
        try:
            params["c"] = int(city_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="city_id должен быть числом")
        sets.append("city_id = :c")

    res = await db.execute(
        text("UPDATE ref.telegram_channels SET " + ", ".join(sets) + " WHERE channel_id = :id"),
        params,
    )
    if not res.rowcount:
        raise HTTPException(status_code=404, detail="канал не найден")
    await db.commit()
    await write_audit(
        db, request, actor, "channel.bind", target=str(channel_id),
        params={"venue_name": venue_name, "venue_address": venue_address, "city_id": params.get("c")},
        result="ok",
    )
    return {"ok": True}
