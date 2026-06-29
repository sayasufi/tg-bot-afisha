"""Admin-панель: «Аналитика» — таймсерии с выбором интервала и авто-бакетом.

Интервал: today | yesterday | 7d | 14d | 30d | 90d | custom(from,to). Бакет авто по длине окна:
≤3 дней → по ЧАСАМ, ≤31 → по ДНЯМ, иначе → по МЕСЯЦАМ. Действия (click/route/share) из Redis
(часовые ключи intent:acth для часового бакета, дневные intent:act иначе); рост (новые юзеры/события)
из PG created_at с date_trunc. KPI-сводка за период. Метки времени в МСК (UTC+3), данные хранятся в UTC.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.services.admin_auth import require_admin
from core.db.session import get_async_db
from core.infra.redis import get_redis

router = APIRouter(prefix="/v1/admin", tags=["admin"])

_KINDS = ("click", "route", "share")
_MSK = timezone(timedelta(hours=3))
_PRESET_DAYS = {"7d": 7, "14d": 14, "30d": 30, "90d": 90}


def _isoweek(dt: datetime) -> str:
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


def _bounds(rng: str, frm: str | None, to: str | None, now: datetime) -> tuple[datetime, datetime]:
    nm = now.astimezone(_MSK)
    midnight = nm.replace(hour=0, minute=0, second=0, microsecond=0)
    if rng == "today":
        return midnight.astimezone(timezone.utc), now
    if rng == "yesterday":
        return (midnight - timedelta(days=1)).astimezone(timezone.utc), midnight.astimezone(timezone.utc)
    if rng == "custom" and frm and to:
        try:
            s = datetime.fromisoformat(frm.replace("Z", "+00:00"))
            e = datetime.fromisoformat(to.replace("Z", "+00:00"))
            if s.tzinfo is None:
                s = s.replace(tzinfo=timezone.utc)
            if e.tzinfo is None:
                e = e.replace(tzinfo=timezone.utc)
            return s.astimezone(timezone.utc), e.astimezone(timezone.utc)
        except Exception:
            pass
    days = _PRESET_DAYS.get(rng, 14)
    return now - timedelta(days=days), now


def _bucket(span_s: float) -> str:
    d = span_s / 86400.0
    return "hour" if d <= 3 else "day" if d <= 31 else "month"


def _first_of_next_month(t: datetime) -> datetime:
    return (t.replace(day=28) + timedelta(days=4)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _buckets(start: datetime, end: datetime, bucket: str) -> list[dict]:
    """Список бакетов: {label (МСК), start (UTC, = date_trunc), akeys: [(ns, keysuffix)]}."""
    out: list[dict] = []
    if bucket == "hour":
        t = start.replace(minute=0, second=0, microsecond=0)
        while t < end:
            out.append({"label": (t + timedelta(hours=3)).strftime("%H:00"), "start": t,
                        "akeys": [("acth", t.strftime("%Y-%m-%d-%H"))]})
            t += timedelta(hours=1)
    elif bucket == "day":
        t = start.replace(hour=0, minute=0, second=0, microsecond=0)
        while t < end:
            out.append({"label": t.strftime("%d.%m"), "start": t, "akeys": [("act", t.strftime("%Y-%m-%d"))]})
            t += timedelta(days=1)
    else:  # month
        t = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        day0 = start.replace(hour=0, minute=0, second=0, microsecond=0)
        while t < end:
            nxt = _first_of_next_month(t)
            keys, dd = [], t
            while dd < nxt and dd < end:
                if dd >= day0:
                    keys.append(("act", dd.strftime("%Y-%m-%d")))
                dd += timedelta(days=1)
            out.append({"label": t.strftime("%m.%y"), "start": t, "akeys": keys})
            t = nxt
    return out


async def _pg_series(db: AsyncSession, table: str, bucket: str, start: datetime, end: datetime, buckets: list[dict]) -> list[dict]:
    rows = (await db.execute(text(
        f"SELECT date_trunc(:b, created_at) AS t, count(*) AS n FROM {table} "
        "WHERE created_at >= :s AND created_at < :e GROUP BY 1"
    ), {"b": bucket, "s": start, "e": end})).all()
    m = {r[0].timestamp(): int(r[1]) for r in rows}
    return [{"label": bk["label"], "value": m.get(bk["start"].timestamp(), 0)} for bk in buckets]


@router.get("/stats/timeseries")
async def timeseries(
    range: str = "14d", frm: str | None = None, to: str | None = None,
    actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db),
) -> dict:
    now = datetime.now(timezone.utc)
    start, end = _bounds(range, frm, to, now)
    if end <= start:
        end = start + timedelta(hours=1)
    bucket = _bucket((end - start).total_seconds())
    buckets = _buckets(start, end, bucket)

    out: dict = {"range": range, "bucket": bucket, "from": start.isoformat(), "to": end.isoformat(),
                 "wau": [], "actions": {}, "new_users": [], "new_events": [], "kpi": {}}

    # действия из Redis
    client = get_redis(decode=True)
    act_totals = {k: 0 for k in _KINDS}
    if client is not None and buckets:
        for kind in _KINDS:
            try:
                pipe = client.pipeline()
                flat = [(bi, ns, sfx) for bi, bk in enumerate(buckets) for (ns, sfx) in bk["akeys"]]
                for _bi, ns, sfx in flat:
                    pipe.get(f"intent:{ns}:{kind}:{sfx}")
                raw = await pipe.execute()
            except Exception:
                raw = [None] * 0
                flat = []
            vals = [0] * len(buckets)
            for (bi, _ns, _sfx), v in zip(flat, raw):
                n = int(v) if v and str(v).lstrip("-").isdigit() else 0
                vals[bi] += n
            out["actions"][kind] = [{"label": bk["label"], "value": vals[i]} for i, bk in enumerate(buckets)]
            act_totals[kind] = sum(vals)
        # WAU — ISO-недели, пересекающие интервал (минимум одна)
        weeks, t = [], start
        while t <= end:
            wk = _isoweek(t)
            if wk not in weeks:
                weeks.append(wk)
            t += timedelta(days=1)
        if not weeks:
            weeks = [_isoweek(end)]
        try:
            pipe = client.pipeline()
            for w in weeks:
                pipe.scard(f"intent:wau:{w}")
            counts = await pipe.execute()
        except Exception:
            counts = [0] * len(weeks)
        out["wau"] = [{"label": w.split("-W")[1], "value": int(n or 0)} for w, n in zip(weeks, counts)]

    out["new_users"] = await _pg_series(db, "ref.users", bucket, start, end, buckets)
    out["new_events"] = await _pg_series(db, "events.events", bucket, start, end, buckets)

    # KPI за период
    new_users = (await db.execute(text("SELECT count(*) FROM ref.users WHERE created_at >= :s AND created_at < :e"), {"s": start, "e": end})).scalar()
    new_events = (await db.execute(text("SELECT count(*) FROM events.events WHERE created_at >= :s AND created_at < :e"), {"s": start, "e": end})).scalar()
    active = (await db.execute(text("SELECT count(*) FROM ref.users WHERE last_active_at >= :s AND last_active_at < :e"), {"s": start, "e": end})).scalar()
    out["kpi"] = {
        "opens": act_totals["click"], "routes": act_totals["route"], "shares": act_totals["share"],
        "new_users": int(new_users or 0), "new_events": int(new_events or 0), "active_users": int(active or 0),
    }
    return out
