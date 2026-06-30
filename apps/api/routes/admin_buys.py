"""Admin-панель: вкладка «Закупки» — учёт реальных размещений рекламы.

Одна строка = одна закупка: канал, цена, время выхода, статус, метка аттрибуции (src_tag). По src_tag
считаем «привёл» (юзеры с acq_source=src_tag) + онбординг/активных → CPV. require_admin, всё в аудит.
"""
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.services.admin_auth import require_admin, write_audit
from core.db.session import get_async_db

router = APIRouter(prefix="/v1/admin", tags=["admin"])
_BOT_USERNAME = "okrestmap_bot"
_UUID = re.compile(r"^[0-9a-fA-F-]{36}$")
_TAG = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_STATUSES = {"planned", "paid", "live", "done", "cancelled"}


def _bid(buy_id: str) -> str:
    if not _UUID.match(buy_id):
        raise HTTPException(status_code=400, detail="bad id")
    return buy_id


def _tag(channel: str, raw: str | None) -> str:
    t = (raw or channel).strip().lstrip("@")
    if not _TAG.match(t):
        raise HTTPException(status_code=422, detail="метка: латиница/цифры/_/-, до 64")
    return t


def _parse_at(raw):
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        raise HTTPException(status_code=422, detail="ad_at: ISO-дата/время")


@router.get("/buys")
async def list_buys(actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db)) -> dict:
    rows = (await db.execute(text(
        "SELECT b.id::text, b.channel_username, b.src_tag, b.price, b.ad_at, b.status, b.note, b.created_at, "
        "  (SELECT count(*) FROM ref.users u WHERE u.acq_source = b.src_tag) AS acquired, "
        "  (SELECT count(*) FROM ref.users u WHERE u.acq_source = b.src_tag AND u.onboarded) AS onboarded, "
        "  (SELECT count(*) FROM ref.users u WHERE u.acq_source = b.src_tag "
        "      AND u.last_active_at > now() - interval '7 days') AS active7 "
        "FROM adstat.ad_buys b ORDER BY b.created_at DESC"
    ))).all()
    items = [{
        "id": r[0], "channel_username": r[1], "src_tag": r[2], "price": r[3],
        "ad_at": r[4].isoformat() if r[4] else None, "status": r[5], "note": r[6],
        "created_at": r[7].isoformat() if r[7] else None,
        "acquired": int(r[8] or 0), "onboarded": int(r[9] or 0), "active7": int(r[10] or 0),
        "cpv": round(r[3] / r[8], 1) if (r[3] and r[8]) else None,
    } for r in rows]
    return {"items": items, "bot_username": _BOT_USERNAME}


@router.post("/buys")
async def create_buy(
    request: Request, payload: dict = Body(...),
    actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db),
) -> dict:
    channel = (payload.get("channel_username") or "").strip().lstrip("@")
    if not channel:
        raise HTTPException(status_code=422, detail="нужен канал (@username)")
    src_tag = _tag(channel, payload.get("src_tag"))
    price = payload.get("price")
    price = int(price) if isinstance(price, (int, float)) and price >= 0 else None
    ad_at = _parse_at(payload.get("ad_at"))
    status = (payload.get("status") or "planned").strip()
    if status not in _STATUSES:
        status = "planned"
    bid = (await db.execute(text(
        "INSERT INTO adstat.ad_buys (channel_username, src_tag, price, ad_at, status, note, created_by) "
        "VALUES (:ch, :tag, :pr, :at, :st, :note, :by) RETURNING id::text"
    ), {"ch": channel, "tag": src_tag, "pr": price, "at": ad_at, "st": status,
        "note": (payload.get("note") or "").strip() or None, "by": actor})).scalar()
    await db.commit()
    await write_audit(db, request, actor, "buy.create", target=bid, params={"channel": channel, "src_tag": src_tag}, result="ok")
    return {"id": bid, "src_tag": src_tag}


@router.patch("/buys/{buy_id}")
async def update_buy(
    buy_id: str, request: Request, payload: dict = Body(...),
    actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db),
) -> dict:
    _bid(buy_id)
    sets, params = [], {"id": buy_id}
    if "status" in payload:
        st = (payload.get("status") or "").strip()
        if st not in _STATUSES:
            raise HTTPException(status_code=422, detail="статус: planned|paid|live|done|cancelled")
        sets.append("status = :st"); params["st"] = st
    if "price" in payload:
        pr = payload.get("price")
        sets.append("price = :pr"); params["pr"] = int(pr) if isinstance(pr, (int, float)) and pr >= 0 else None
    if "ad_at" in payload:
        sets.append("ad_at = :at"); params["at"] = _parse_at(payload.get("ad_at"))
    if "note" in payload:
        sets.append("note = :note"); params["note"] = (payload.get("note") or "").strip() or None
    if not sets:
        raise HTTPException(status_code=400, detail="нечего менять")
    sets.append("updated_at = now()")
    res = await db.execute(text(f"UPDATE adstat.ad_buys SET {', '.join(sets)} WHERE id = CAST(:id AS uuid)"), params)
    if not res.rowcount:
        raise HTTPException(status_code=404, detail="закупка не найдена")
    await db.commit()
    await write_audit(db, request, actor, "buy.update", target=buy_id, result="ok")
    return {"ok": True}


@router.delete("/buys/{buy_id}")
async def delete_buy(
    buy_id: str, request: Request,
    actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db),
) -> dict:
    _bid(buy_id)
    res = await db.execute(text("DELETE FROM adstat.ad_buys WHERE id = CAST(:id AS uuid)"), {"id": buy_id})
    if not res.rowcount:
        raise HTTPException(status_code=404, detail="закупка не найдена")
    await db.commit()
    await write_audit(db, request, actor, "buy.delete", target=buy_id, result="ok")
    return {"ok": True}
