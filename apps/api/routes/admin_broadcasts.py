"""Admin-панель: вкладка «Рассылки» — счётчики получателей + ТЕСТ дайджеста/напоминания СЕБЕ.

БЕЗОПАСНОСТЬ: тест шлёт ТОЛЬКО на admin_test_user_id (@throlib). Тройной гард: (1) endpoint 400 если id не
задан; (2) only_user_id передаётся СТРОГО этим id; (3) impl-ы (_send_digest_impl/send_test_reminder)
фильтруют получателей жёстко по этому id. Боевые рассылки ТУТ НЕ запускаются — недельный дайджест и
напоминания идут по расписанию (раздел Процессы), там же их можно прогнать вручную осознанно.

NB: импорт worker-impl (apps.worker) из apps.api — СОЗНАТЕЛЬНОЕ исключение из изоляции сервисов: тест
«себе» удобнее синхронно (мгновенный ответ + счётчик отправленного), чем триггерить Prefect-флоу.
"""
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.services.admin_auth import require_admin, write_audit
from apps.worker.tasks.digest import _send_digest_impl
from apps.worker.tasks.reminders import send_test_reminder
from core.config.settings import get_settings
from core.db.session import get_async_db

router = APIRouter(prefix="/v1/admin", tags=["admin"])


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
