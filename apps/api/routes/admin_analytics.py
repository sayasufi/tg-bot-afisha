"""Admin-панель: вкладка «Аналитика» — таймсерии трендов.

WAU (8 ISO-недель) и действия по видам (14 дней) — из Redis-ключей intent.py (как /v1/stats). Рост каталога
и пользователей (14 дней) — из created_at в PG. Всё агрегаты, без персональных данных. require_admin.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.services.admin_auth import require_admin
from core.db.session import get_async_db
from core.infra.redis import get_redis

router = APIRouter(prefix="/v1/admin", tags=["admin"])

_KINDS = ("click", "route", "share", "reminder", "calendar")
_WEEKS = 8
_DAYS = 14


def _isoweek(dt: datetime) -> str:
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


async def _daily(db: AsyncSession, table: str) -> list[dict]:
    """Кол-во строк по дням за 14 дней (created_at). table — литерал из кода (не пользовательский ввод)."""
    rows = (await db.execute(text(
        f"SELECT date_trunc('day', created_at) AS d, count(*) AS n FROM {table} "
        "WHERE created_at > now() - interval '14 days' "
        "GROUP BY date_trunc('day', created_at) ORDER BY date_trunc('day', created_at)"
    ))).all()
    return [{"label": r[0].strftime("%d.%m"), "value": int(r[1])} for r in rows]


@router.get("/stats/timeseries")
async def timeseries(actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db)) -> dict:
    now = datetime.now(timezone.utc)
    out: dict = {"wau": [], "actions": {}, "new_users": [], "new_events": []}

    client = get_redis(decode=True)
    if client is not None:
        weeks = [_isoweek(now - timedelta(weeks=i)) for i in range(_WEEKS - 1, -1, -1)]  # oldest → newest
        try:
            pipe = client.pipeline()
            for w in weeks:
                pipe.scard(f"intent:wau:{w}")
            counts = await pipe.execute()
        except Exception:
            counts = [0] * len(weeks)
        out["wau"] = [{"label": w.split("-W")[1], "value": int(n or 0)} for w, n in zip(weeks, counts)]

        days = [now - timedelta(days=i) for i in range(_DAYS - 1, -1, -1)]
        daystrs = [d.strftime("%Y-%m-%d") for d in days]
        for kind in _KINDS:
            try:
                pipe = client.pipeline()
                for ds in daystrs:
                    pipe.get(f"intent:act:{kind}:{ds}")
                raw = await pipe.execute()
            except Exception:
                raw = [None] * len(daystrs)
            out["actions"][kind] = [
                {"label": d.strftime("%d.%m"), "value": int(v) if v and str(v).lstrip("-").isdigit() else 0}
                for d, v in zip(days, raw)
            ]

    try:
        out["new_users"] = await _daily(db, "ref.users")
    except Exception:
        pass
    try:
        out["new_events"] = await _daily(db, "events.events")
    except Exception:
        pass
    return out
