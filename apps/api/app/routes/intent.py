"""North-star telemetry: weekly users who take a real INTENT action.

The product's north-star is "weekly users who take a real intent action" — opening a
route to a venue, clicking through to the source/tickets, setting a reminder, or adding
to calendar. Those are the moments with economic value (they prove the app drove a
real-world outcome), unlike a favourite or a map open. This endpoint records them.

Aggregate-only by design: a weekly SET of user ids (the north-star numerator) + per-kind
daily counters + a per-event counter — no per-user-per-event surveillance. Best-effort:
telemetry must never fail or slow the caller, so every Redis error is swallowed.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Response
from pydantic import BaseModel

from apps.api.app.services.telegram_auth import validate_init_data
from core.redis import get_redis

router = APIRouter(prefix="/v1", tags=["intent"])

_KINDS = {"click", "route", "share", "reminder", "calendar"}
_WAU_TTL = 5 * 7 * 24 * 3600  # keep ~5 weekly sets, then they self-expire
_ACT_TTL = 120 * 24 * 3600


class IntentRequest(BaseModel):
    kind: str
    event_id: str | None = None
    init_data: str | None = None  # signed Telegram initData → identifies the weekly user


@router.post("/intent", status_code=204)
async def log_intent(payload: IntentRequest) -> Response:
    kind = (payload.kind or "").strip().lower()
    if kind not in _KINDS:
        return Response(status_code=204)  # unknown kind → ignore (forward-compatible)
    client = get_redis(decode=True)
    if client is not None:
        try:
            now = datetime.now(timezone.utc)
            day = now.strftime("%Y-%m-%d")
            y, w, _ = now.isocalendar()
            week = f"{y}-W{w:02d}"
            uid = None
            if payload.init_data:
                try:
                    uid = (validate_init_data(payload.init_data) or {}).get("id")
                except Exception:  # invalid/expired initData → count the action, not the user
                    uid = None
            pipe = client.pipeline()
            pipe.incr(f"intent:act:{kind}:{day}")
            pipe.expire(f"intent:act:{kind}:{day}", _ACT_TTL)
            if uid is not None:
                pipe.sadd(f"intent:wau:{week}", str(uid))
                pipe.expire(f"intent:wau:{week}", _WAU_TTL)
            if payload.event_id:
                pipe.hincrby("intent:event", payload.event_id, 1)
            await pipe.execute()
        except Exception:  # pragma: no cover — telemetry is best-effort
            pass
    return Response(status_code=204)
