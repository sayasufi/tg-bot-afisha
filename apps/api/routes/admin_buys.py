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
    return t.lower()  # M10: lowercase — чтобы метка точно совпала с acq_source юзера (тоже lowercase)


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
    # M11: активность/удержание считаем по last_app_open_at (реальное открытие приложения), а НЕ last_active_at —
    # последнее бьётся и бот-командами (/start на DM-дайджест) и завышало бы retention.
    rows = (await db.execute(text(
        "SELECT b.id::text, b.channel_username, b.src_tag, b.price, b.ad_at, b.status, b.note, b.created_at, "
        "  (SELECT count(*) FROM ref.users u WHERE u.acq_source = b.src_tag) AS acquired, "
        "  (SELECT count(*) FROM ref.users u WHERE u.acq_source = b.src_tag AND u.onboarded) AS onboarded, "
        "  (SELECT count(*) FROM ref.users u WHERE u.acq_source = b.src_tag "
        "      AND u.last_app_open_at > now() - interval '7 days') AS active7, "
        # удержан = пришёл по каналу И открывал приложение спустя ≥2 дня после захода (не разовый открыл-закрыл)
        "  (SELECT count(*) FROM ref.users u WHERE u.acq_source = b.src_tag AND u.acq_at IS NOT NULL "
        "      AND u.last_app_open_at > u.acq_at + interval '2 days') AS retained "
        "FROM adstat.ad_buys b ORDER BY b.created_at DESC"
    ))).all()
    items = [{
        "id": r[0], "channel_username": r[1], "src_tag": r[2], "price": r[3],
        "ad_at": r[4].isoformat() if r[4] else None, "status": r[5], "note": r[6],
        "created_at": r[7].isoformat() if r[7] else None,
        "acquired": int(r[8] or 0), "onboarded": int(r[9] or 0), "active7": int(r[10] or 0), "retained": int(r[11] or 0),
        "cpv": round(r[3] / r[8], 1) if (r[3] and r[8]) else None,            # цена за пришедшего
        "cpr": round(r[3] / r[11], 1) if (r[3] and r[11]) else None,          # цена за удержанного (главная ROI-метрика)
    } for r in rows]
    spent = sum(b["price"] or 0 for b in items if b["status"] != "cancelled")
    # M12: суммарные «пришло/удержано» — COUNT(DISTINCT) по тегам АКТИВНЫХ закупок, а не sum по строкам:
    # две закупки с одной меткой считали бы одних юзеров дважды и занижали сводный CPV/CPR.
    sm = (await db.execute(text(
        "SELECT "
        "  count(DISTINCT u.telegram_user_id) FILTER (WHERE u.telegram_user_id IS NOT NULL), "
        "  count(DISTINCT u.telegram_user_id) FILTER (WHERE u.acq_at IS NOT NULL "
        "      AND u.last_app_open_at > u.acq_at + interval '2 days') "
        "FROM ref.users u WHERE u.acq_source IN "
        "  (SELECT src_tag FROM adstat.ad_buys WHERE status <> 'cancelled')"
    ))).first()
    came, retained = int(sm[0] or 0), int(sm[1] or 0)
    by_status: dict = {}
    for b in items:
        by_status[b["status"]] = by_status.get(b["status"], 0) + 1
    summary = {
        "spent": spent, "came": came, "retained": retained,
        "cpv": round(spent / came, 1) if came else None,
        "cpr": round(spent / retained, 1) if retained else None,
        "by_status": by_status,
    }
    return {"items": items, "summary": summary, "bot_username": _BOT_USERNAME}


@router.get("/buy-plan")
async def buy_plan(
    city: str = "", actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db),
) -> dict:
    """Ранжированный шорт-лист каналов К ЗАКУПКЕ: on-topic, вердикт брать/осторожно, с известной ценой —
    полный разбор сигналов (ERR, реакции, CPM, охват, город). Жадную раскладку под бюджет делает фронт."""
    rk = "(CASE source WHEN 'tme' THEN 4 WHEN 'telethon' THEN 3 WHEN 'telemetr' THEN 2 ELSE 1 END)"
    params: dict = {"r": ["афиша", "город/локалка"], "v": ["брать", "осторожно"]}
    city_clause = ""
    if city.strip():
        city_clause = "AND c.city = :city "
        params["city"] = city.strip()
    rows = (await db.execute(text(
        "SELECT c.username, c.city, c.score, c.verdict, c.ad_price, "
        "  sub.subscribers, rch.avg_reach, rea.avg_reactions, "
        "  (SELECT count(*) FROM ref.users u WHERE u.acq_source = c.username) AS acquired, c.relevance "
        "FROM adstat.channels c "
        f"LEFT JOIN LATERAL (SELECT subscribers FROM adstat.snapshots s WHERE s.channel_id=c.channel_id AND s.subscribers IS NOT NULL ORDER BY {rk} DESC, captured_at DESC LIMIT 1) sub ON true "
        f"LEFT JOIN LATERAL (SELECT avg_reach FROM adstat.snapshots s WHERE s.channel_id=c.channel_id AND s.avg_reach IS NOT NULL ORDER BY {rk} DESC, captured_at DESC LIMIT 1) rch ON true "
        f"LEFT JOIN LATERAL (SELECT avg_reactions FROM adstat.snapshots s WHERE s.channel_id=c.channel_id AND s.avg_reactions IS NOT NULL ORDER BY {rk} DESC, captured_at DESC LIMIT 1) rea ON true "
        "WHERE c.relevance = ANY(:r) AND c.verdict = ANY(:v) AND c.ad_price > 0 "
        f"{city_clause}"
        "ORDER BY c.score DESC NULLS LAST LIMIT 150"
    ), params)).all()
    items = []
    for r in rows:
        subs, reach, reactions, price = r[5], r[6], r[7], r[4]
        items.append({
            "username": r[0], "city": r[1], "score": r[2], "verdict": r[3], "price": price,
            "relevance": r[9],
            "subscribers": subs, "reach": reach, "reactions": reactions, "acquired": int(r[8] or 0),
            "err": round(reach / subs * 100, 1) if (subs and reach) else None,
            "rrate": round(reactions / reach * 100, 2) if (reactions and reach) else None,
            "cpm": round(price / reach * 1000) if (price and reach) else None,
        })
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
