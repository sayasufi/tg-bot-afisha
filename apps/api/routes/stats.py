"""Owner-only north-star readout — GET /v1/stats?token=...

A tiny private dashboard for the product's north-star ("weekly users who take a real
intent action", see routes/intent.py): WAU over the last few ISO weeks, per-kind action
totals over the last 7 days, and the top events by intent. Aggregate-only — it reads the
same Redis keys intent.py writes, never per-user data.

GATE: a shared token. There is no admin secret in settings, so this reads STATS_TOKEN
straight from the environment. It DEFAULTS TO DISABLED — if STATS_TOKEN is unset/empty the
endpoint always returns 404 (it doesn't even exist as far as a caller can tell), so it can
never be left open by accident. Best-effort on Redis: any hiccup degrades to zeros, the
token check still holds.
"""
import hmac
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from core.infra.redis import get_redis

router = APIRouter(prefix="/v1", tags=["stats"])

_KINDS = ("click", "route", "share", "reminder", "calendar")
_WEEKS_BACK = 4   # current + previous 3 ISO weeks
_DAYS_BACK = 7    # action totals window
_TOP_EVENTS = 10


def _require_token(token: str | None) -> None:
    """Constant-time token check. Disabled (→ 404) unless STATS_TOKEN is set non-empty —
    a 404 (not 403) so an unauthorized caller can't even tell the route exists."""
    expected = (os.environ.get("STATS_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status_code=404)  # never open when unconfigured
    # token.isascii() first: hmac.compare_digest raises TypeError on non-ASCII input, which
    # would surface as a 500 (leaking that the route exists + a token is set). A non-ASCII
    # token can never match the env token, so reject it as a plain 404.
    if not token or not token.isascii() or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=404)


@router.get("/stats")
async def stats(token: str | None = Query(default=None)) -> dict:
    _require_token(token)

    now = datetime.now(timezone.utc)
    out: dict = {
        "as_of": now.isoformat(),
        "wau": [],          # [{week, users}] most-recent first
        "actions_7d": {},   # {kind: total}
        "top_events": [],   # [{event_id, count}]
    }

    client = get_redis(decode=True)
    if client is None:
        # Degrade to a well-formed, zeroed payload so the readout never errors on a Redis
        # outage (the token gate already passed).
        out["wau"] = [{"week": _isoweek(now - timedelta(weeks=i)), "users": 0} for i in range(_WEEKS_BACK)]
        out["actions_7d"] = {k: 0 for k in _KINDS}
        return out

    # WAU — SCARD the weekly SETs (current + previous ~3 ISO weeks).
    weeks = [_isoweek(now - timedelta(weeks=i)) for i in range(_WEEKS_BACK)]
    try:
        pipe = client.pipeline()
        for w in weeks:
            pipe.scard(f"intent:wau:{w}")
        counts = await pipe.execute()
    except Exception:  # pragma: no cover - best-effort
        counts = [0] * len(weeks)
    out["wau"] = [{"week": w, "users": int(n or 0)} for w, n in zip(weeks, counts)]

    # Per-kind action totals over the last 7 days (sum the daily counters).
    days = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(_DAYS_BACK)]
    try:
        pipe = client.pipeline()
        for kind in _KINDS:
            for day in days:
                pipe.get(f"intent:act:{kind}:{day}")
        raw = await pipe.execute()
    except Exception:  # pragma: no cover - best-effort
        raw = [None] * (len(_KINDS) * len(days))
    per_day = len(days)
    out["actions_7d"] = {
        kind: sum(int(v) for v in raw[i * per_day:(i + 1) * per_day] if v is not None and str(v).lstrip("-").isdigit())
        for i, kind in enumerate(_KINDS)
    }

    # Top events by the intent:event hash.
    try:
        events = await client.hgetall("intent:event")
    except Exception:  # pragma: no cover - best-effort
        events = {}
    ranked = sorted(
        ((eid, int(c)) for eid, c in events.items() if str(c).lstrip("-").isdigit()),
        key=lambda kv: kv[1],
        reverse=True,
    )[:_TOP_EVENTS]
    out["top_events"] = [{"event_id": eid, "count": c} for eid, c in ranked]

    return out


def _isoweek(dt: datetime) -> str:
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"
