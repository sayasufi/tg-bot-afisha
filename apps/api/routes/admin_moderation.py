"""Admin moderation queue for user submissions (ref.pending_submissions).

Same shape as the other admin routers: every endpoint behind require_admin (404 when the panel is
disabled), every mutation written to ref.admin_audit (best-effort, no PII in params). Approving an
EVENT ingests it into the pipeline via events.raw_events (see submissions.ingest_event_submission).
"""
import logging

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.services.admin_auth import require_admin, write_audit
from core.config.settings import get_settings
from core.domain.cities import CITIES
from core.render.formatting import ce
from core.db.repositories.submissions import (
    approve_channel_submission,
    count_submissions,
    get_submission,
    ingest_event_submission,
    list_submissions,
    set_status,
)
from core.db.session import get_async_db

router = APIRouter(prefix="/v1/admin/moderation", tags=["admin"])
_log = logging.getLogger(__name__)
_PAGE = 50

# Fixed rejection vocabulary — the honest, short reason the submitter gets (no free text).
_REJECT_REASONS = {
    "duplicate": "это событие уже есть в афише",
    "incomplete": "не хватает данных о событии",
    "not_event": "это не похоже на культурное событие",
    "past": "событие уже прошло",
    "spam": "заявка отклонена",
    "other": "заявка отклонена",
}


async def _dm(uid: int, text_html: str) -> None:
    """Best-effort DM to the submitter (they may not have started the bot → send just fails silently)."""
    token = get_settings().telegram_bot_token
    if not token or not uid:
        return
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            await c.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": int(uid), "text": text_html, "parse_mode": "HTML",
                      "disable_web_page_preview": True},
            )
    except Exception:
        pass


@router.get("/queue")
async def queue(
    status: str = "needs_review",
    kind: str | None = None,
    page: int = 1,
    actor: str = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    page = max(1, page)
    status_f = status or None
    items = await list_submissions(db, status=status_f, kind=kind, limit=_PAGE, offset=(page - 1) * _PAGE)
    total = await count_submissions(db, status=status_f, kind=kind)
    # Pending counts for the nav badge / tabs.
    pending = await count_submissions(db, status="needs_review", kind=None)
    return {"items": items, "total": total, "page": page, "page_size": _PAGE, "pending": pending}


@router.post("/{submission_id}/approve")
async def approve(
    submission_id: str,
    request: Request,
    city_slug: str | None = Body(None, embed=True),
    actor: str = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    sub = await get_submission(db, submission_id)
    if not sub:
        raise HTTPException(status_code=404, detail="not found")
    if sub["status"] not in ("needs_review", "auto_rejected"):
        raise HTTPException(status_code=409, detail=f"уже обработано ({sub['status']})")

    if sub["kind"] == "channel":
        if city_slug and city_slug in CITIES:
            sub["city_slug"] = city_slug  # admin corrected the channel's city before approving
        channel_id = await approve_channel_submission(db, sub)
        await set_status(db, submission_id, "approved", reviewed_by=actor, target_channel_id=channel_id)
        await write_audit(
            db, request, actor, "moderation.approve",
            target=submission_id, params={"kind": "channel", "channel_id": channel_id}, result="ok",
        )
        uname = (sub.get("data") or {}).get("username_norm") or ""
        await _dm(
            int(sub["submitted_by"]),
            f"{ce('✨')} <b>Спасибо!</b> Канал @{uname} добавлен — события из него появятся на карте в течение суток.",
        )
        return {"ok": True, "status": "approved", "channel_id": channel_id}

    raw_id = await ingest_event_submission(db, sub)
    await set_status(db, submission_id, "approved", reviewed_by=actor, target_raw_id=raw_id)
    await write_audit(
        db, request, actor, "moderation.approve",
        target=submission_id, params={"kind": sub["kind"], "raw_id": raw_id}, result="ok",
    )
    await _dm(
        int(sub["submitted_by"]),
        f"{ce('✨')} <b>Спасибо!</b> Твоё событие одобрено — появится на карте в течение часа.",
    )
    return {"ok": True, "status": "approved", "raw_id": raw_id}


@router.post("/{submission_id}/reject")
async def reject(
    submission_id: str,
    request: Request,
    reject_code: str = Body("other", embed=True),
    actor: str = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    sub = await get_submission(db, submission_id)
    if not sub:
        raise HTTPException(status_code=404, detail="not found")
    if sub["status"] in ("rejected", "ingested"):
        raise HTTPException(status_code=409, detail=f"уже обработано ({sub['status']})")
    code = reject_code if reject_code in _REJECT_REASONS else "other"
    await set_status(db, submission_id, "rejected", reviewed_by=actor, reject_code=code)
    await write_audit(
        db, request, actor, "moderation.reject",
        target=submission_id, params={"kind": sub["kind"], "reject_code": code}, result="ok",
    )
    await _dm(
        int(sub["submitted_by"]),
        f"{ce('📍')} Спасибо за заявку! В этот раз не добавили: {_REJECT_REASONS[code]}. "
        "Пробуй ещё — мы рады новым событиям.",
    )
    return {"ok": True, "status": "rejected", "reject_code": code}
