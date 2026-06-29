"""Admin-панель: вкладка «Рассылки» — счётчики получателей + ТЕСТ дайджеста/напоминания СЕБЕ.

БЕЗОПАСНОСТЬ: тест шлёт ТОЛЬКО на admin_test_user_id (@throlib). Тройной гард: (1) endpoint 400 если id не
задан; (2) only_user_id передаётся СТРОГО этим id; (3) impl-ы (_send_digest_impl/send_test_reminder)
фильтруют получателей жёстко по этому id. Боевые рассылки ТУТ НЕ запускаются — недельный дайджест и
напоминания идут по расписанию (раздел Процессы), там же их можно прогнать вручную осознанно.

NB: импорт worker-impl (apps.worker) из apps.api — СОЗНАТЕЛЬНОЕ исключение из изоляции сервисов: тест
«себе» удобнее синхронно (мгновенный ответ + счётчик отправленного), чем триггерить Prefect-флоу.
"""
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.services.admin_auth import require_admin, write_audit
from apps.worker.tasks.broadcasts import audience_count, send_campaign_impl
from apps.worker.tasks.digest import _send_digest_impl
from apps.worker.tasks.reminders import send_test_reminder
from core.config.settings import get_settings
from core.db.session import get_async_db

router = APIRouter(prefix="/v1/admin", tags=["admin"])

_UUID = re.compile(r"^[0-9a-fA-F-]{36}$")
_AUD_KINDS = {"all", "opted_in", "city", "active_since"}


def _cid(campaign_id: str) -> str:
    if not _UUID.match(campaign_id):
        raise HTTPException(status_code=400, detail="bad campaign id")
    return campaign_id


def _clean_audience(a: dict | None) -> dict:
    a = a or {}
    kind = a.get("kind", "opted_in")
    if kind not in _AUD_KINDS:
        raise HTTPException(status_code=422, detail="audience.kind: all|opted_in|city|active_since")
    out: dict = {"kind": kind}
    if kind == "city":
        out["cities"] = [c for c in (a.get("cities") or []) if isinstance(c, str)][:50]
    if kind == "active_since":
        out["since_days"] = max(1, min(365, int(a.get("since_days") or 7)))
    return out


def _valid_button(label, url):
    label = (label or "").strip() or None
    url = (url or "").strip() or None
    if not label and not url:
        return None, None
    if not (label and url):
        raise HTTPException(status_code=422, detail="кнопка: нужны и текст, и ссылка")
    if not re.match(r"^https://", url):
        raise HTTPException(status_code=422, detail="ссылка кнопки должна начинаться с https://")
    return label[:64], url[:512]


async def _gate(db: AsyncSession, campaign_id: str, payload: dict) -> None:
    """Жёсткая стена перед боевой отправкой: тест отправлен + явное подтверждение + эхо числа получателей
    совпадает со свежим dry-run (нельзя подтвердить «N», а отправить другой аудитории)."""
    c = (await db.execute(text(
        "SELECT status, test_sent_at, audience FROM ref.broadcast_campaigns WHERE id=CAST(:id AS uuid)"
    ), {"id": campaign_id})).mappings().first()
    if c is None:
        raise HTTPException(status_code=404, detail="кампания не найдена")
    if c["test_sent_at"] is None:
        raise HTTPException(status_code=400, detail="Сначала отправьте ТЕСТ себе и проверьте его")
    if payload.get("confirm") is not True:
        raise HTTPException(status_code=400, detail="Нужно явное подтверждение боевой отправки")
    expected = payload.get("expected_count")
    if not isinstance(expected, int):
        raise HTTPException(status_code=400, detail="Нет подтверждённого числа получателей")
    audience = c["audience"] if isinstance(c["audience"], dict) else {}
    fresh, _ = await audience_count(db, audience)
    if abs(expected - fresh) > max(5, fresh * 0.05):
        raise HTTPException(status_code=409, detail=f"Аудитория изменилась (подтверждали {expected}, сейчас {fresh}) — перепроверьте")


@router.get("/broadcast/recipients")
async def broadcast_recipients(actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db)) -> dict:
    """Сколько кого: всего юзеров, подписаны на дайджест, не отключали напоминания, активны за 7д."""
    r = (await db.execute(text(
        "SELECT count(*) total, "
        "count(*) FILTER (WHERE notify_digest) digest_optin, "
        "count(*) FILTER (WHERE notify_reminders) reminder_optin, "
        "count(*) FILTER (WHERE last_active_at > now() - interval '7 days') active_7d "
        "FROM ref.users"
    ))).first()
    return {
        "total": int(r[0] or 0),
        "digest_optin": int(r[1] or 0),
        "reminder_optin": int(r[2] or 0),
        "active_7d": int(r[3] or 0),
        "test_user_id": get_settings().admin_test_user_id or None,
    }


@router.post("/broadcast/test")
async def broadcast_test(
    request: Request,
    payload: dict = Body(...),
    actor: str = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """ТЕСТ СЕБЕ: дайджест-превью или напоминание-превью ТОЛЬКО на admin_test_user_id. kind: digest|reminder."""
    uid = get_settings().admin_test_user_id
    if not uid:
        raise HTTPException(status_code=400, detail="ADMIN_TEST_USER_ID не задан — тест-кнопки выключены")
    kind = (payload.get("kind") or "").strip()
    if kind == "digest":
        sent = await _send_digest_impl(only_user_id=uid)
    elif kind == "reminder":
        sent = await send_test_reminder(uid)
    else:
        raise HTTPException(status_code=400, detail="kind: digest | reminder")
    await write_audit(db, request, actor, "broadcast.test", target=kind, params={"user_id": uid, "sent": sent}, result="ok")
    return {"ok": True, "kind": kind, "sent": sent, "to": uid}


# ---- кастомные кампании --------------------------------------------------------------------------

_CAMP_COLS = ("id::text, title, body, image_url, button_label, button_url, audience, schedule_kind, "
              "scheduled_at, status, sent_count, failed_count, skipped_count, test_sent_at, confirmed_at, created_at")


def _camp_dict(m) -> dict:
    return {
        "id": m["id"], "title": m["title"], "body": m["body"], "image_url": m["image_url"],
        "button_label": m["button_label"], "button_url": m["button_url"],
        "audience": m["audience"] if isinstance(m["audience"], dict) else {},
        "schedule_kind": m["schedule_kind"], "scheduled_at": m["scheduled_at"].isoformat() if m["scheduled_at"] else None,
        "status": m["status"], "sent_count": m["sent_count"], "failed_count": m["failed_count"],
        "skipped_count": m["skipped_count"], "test_sent_at": m["test_sent_at"].isoformat() if m["test_sent_at"] else None,
        "confirmed_at": m["confirmed_at"].isoformat() if m["confirmed_at"] else None,
        "created_at": m["created_at"].isoformat() if m["created_at"] else None,
    }


@router.get("/broadcast/campaigns")
async def list_campaigns(actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db)) -> dict:
    rows = (await db.execute(text(
        f"SELECT {_CAMP_COLS} FROM ref.broadcast_campaigns ORDER BY created_at DESC LIMIT 100"
    ))).mappings().all()
    return {"items": [_camp_dict(m) for m in rows]}


@router.post("/broadcast/campaigns")
async def create_campaign(
    request: Request, payload: dict = Body(...),
    actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db),
) -> dict:
    title = (payload.get("title") or "").strip()
    body = (payload.get("body") or "").strip()
    if not title or not body:
        raise HTTPException(status_code=422, detail="нужны заголовок и текст")
    audience = _clean_audience(payload.get("audience"))
    blabel, burl = _valid_button(payload.get("button_label"), payload.get("button_url"))
    image_url = (payload.get("image_url") or "").strip() or None
    import json as _json
    cid = (await db.execute(text(
        "INSERT INTO ref.broadcast_campaigns (title, body, image_url, button_label, button_url, audience, created_by) "
        "VALUES (:t, :b, :img, :bl, :bu, CAST(:aud AS jsonb), :by) RETURNING id::text"
    ), {"t": title, "b": body, "img": image_url, "bl": blabel, "bu": burl, "aud": _json.dumps(audience), "by": actor})).scalar()
    await db.commit()
    await write_audit(db, request, actor, "broadcast.create", target=cid, params={"title": title}, result="ok")
    return {"id": cid}


@router.patch("/broadcast/campaigns/{campaign_id}")
async def update_campaign(
    campaign_id: str, request: Request, payload: dict = Body(...),
    actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db),
) -> dict:
    _cid(campaign_id)
    title = (payload.get("title") or "").strip()
    body = (payload.get("body") or "").strip()
    if not title or not body:
        raise HTTPException(status_code=422, detail="нужны заголовок и текст")
    audience = _clean_audience(payload.get("audience"))
    blabel, burl = _valid_button(payload.get("button_label"), payload.get("button_url"))
    image_url = (payload.get("image_url") or "").strip() or None
    import json as _json
    res = await db.execute(text(
        "UPDATE ref.broadcast_campaigns SET title=:t, body=:b, image_url=:img, button_label=:bl, button_url=:bu, "
        "audience=CAST(:aud AS jsonb), updated_at=now() WHERE id=CAST(:id AS uuid) AND status='draft' RETURNING id"
    ), {"t": title, "b": body, "img": image_url, "bl": blabel, "bu": burl, "aud": _json.dumps(audience), "id": campaign_id})
    if not res.rowcount:
        raise HTTPException(status_code=409, detail="редактировать можно только черновик")
    await db.commit()
    await write_audit(db, request, actor, "broadcast.update", target=campaign_id, result="ok")
    return {"ok": True}


@router.post("/broadcast/dry-run")
async def dry_run(
    payload: dict = Body(...), actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db),
) -> dict:
    """Число получателей по аудитории БЕЗ отправки (тот же resolver, что и боевая отправка)."""
    audience = _clean_audience(payload.get("audience"))
    count, by_city = await audience_count(db, audience)
    return {"count": count, "by_city": by_city}


@router.post("/broadcast/campaigns/{campaign_id}/test")
async def test_campaign(
    campaign_id: str, request: Request,
    actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db),
) -> dict:
    """ТЕСТ СЕБЕ: шлёт кампанию СТРОГО на admin_test_user_id. test_sent_at ставится ТОЛЬКО при sent==1
    (так кривой HTML/битая кнопка не пройдут гейт боевой отправки)."""
    _cid(campaign_id)
    uid = get_settings().admin_test_user_id
    if not uid:
        raise HTTPException(status_code=400, detail="ADMIN_TEST_USER_ID не задан")
    res = await send_campaign_impl(campaign_id, only_user_id=uid)
    if res["sent"] == 1:
        await db.execute(text("UPDATE ref.broadcast_campaigns SET test_sent_at=now(), updated_at=now() WHERE id=CAST(:id AS uuid)"), {"id": campaign_id})
        await db.commit()
    await write_audit(db, request, actor, "broadcast.test_campaign", target=campaign_id, params={"to": uid, **res}, result="ok")
    return {"to": uid, **res}


@router.post("/broadcast/campaigns/{campaign_id}/send-now")
async def send_now(
    campaign_id: str, request: Request, payload: dict = Body(...),
    actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db),
) -> dict:
    _cid(campaign_id)
    await _gate(db, campaign_id, payload)
    # RETURNING-гард: подтвердить/запланировать можно ТОЛЬКО черновик → дабл-сабмит не запустит дважды.
    res = await db.execute(text(
        "UPDATE ref.broadcast_campaigns SET status='scheduled', schedule_kind='now', confirmed_at=now(), "
        "updated_at=now() WHERE id=CAST(:id AS uuid) AND status='draft' RETURNING id"
    ), {"id": campaign_id})
    if not res.rowcount:
        raise HTTPException(status_code=409, detail="кампания уже запущена или завершена")
    await db.commit()
    await write_audit(db, request, actor, "broadcast.send_now", target=campaign_id, params={"expected": payload.get("expected_count")}, result="ok")
    return {"ok": True, "status": "scheduled", "note": "уйдёт в течение ~5 минут (диспетчер)"}


@router.post("/broadcast/campaigns/{campaign_id}/schedule")
async def schedule_campaign(
    campaign_id: str, request: Request, payload: dict = Body(...),
    actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db),
) -> dict:
    _cid(campaign_id)
    kind = (payload.get("kind") or "").strip()
    if kind == "at_local":
        raise HTTPException(status_code=400, detail="по местному времени городов — скоро (готовится отдельно)")
    if kind != "at_utc":
        raise HTTPException(status_code=422, detail="kind: at_utc")
    try:
        when = datetime.fromisoformat((payload.get("scheduled_at") or "").replace("Z", "+00:00"))
    except Exception:
        raise HTTPException(status_code=422, detail="scheduled_at: ISO-дата/время")
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    await _gate(db, campaign_id, payload)
    res = await db.execute(text(
        "UPDATE ref.broadcast_campaigns SET status='scheduled', schedule_kind='at_utc', scheduled_at=:at, "
        "confirmed_at=now(), updated_at=now() WHERE id=CAST(:id AS uuid) AND status='draft' RETURNING id"
    ), {"at": when, "id": campaign_id})
    if not res.rowcount:
        raise HTTPException(status_code=409, detail="кампания уже запущена или завершена")
    await db.commit()
    await write_audit(db, request, actor, "broadcast.schedule", target=campaign_id, params={"at": when.isoformat()}, result="ok")
    return {"ok": True, "status": "scheduled", "scheduled_at": when.isoformat()}


@router.post("/broadcast/campaigns/{campaign_id}/cancel")
async def cancel_campaign(
    campaign_id: str, request: Request,
    actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db),
) -> dict:
    _cid(campaign_id)
    res = await db.execute(text(
        "UPDATE ref.broadcast_campaigns SET status='cancelled', updated_at=now() "
        "WHERE id=CAST(:id AS uuid) AND status IN ('draft','scheduled') RETURNING id"
    ), {"id": campaign_id})
    if not res.rowcount:
        raise HTTPException(status_code=409, detail="нельзя отменить (уже идёт отправка или завершена)")
    await db.commit()
    await write_audit(db, request, actor, "broadcast.cancel", target=campaign_id, result="ok")
    return {"ok": True, "status": "cancelled"}
