"""Admin-панель API (admin.okrestmap.ru) — единый authed-роутер /v1/admin/*.

Фаза 1: логин владельца (Telegram Login Widget → подписанная сессия), дашборд-сводка, здоровье инфры.
Дальнейшие фазы (операции/настройки/модерация/рассылки) добавляются сюда же. Каждая защищённая ручка
зависит от require_admin (404 если не сконфигурён/нет сессии — поверхность невидима).
"""
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Body, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from apps.api.services.admin_auth import (
    issue_session,
    require_admin,
    validate_credentials,
    write_audit,
)
from core.config.settings import get_settings
from core.db.session import get_async_db
from core.infra.redis import get_redis

router = APIRouter(prefix="/v1/admin", tags=["admin"])

_KINDS = ("click", "route", "share", "reminder", "calendar")
_WEEKS_BACK = 4
_DAYS_BACK = 7


def _isoweek(dt: datetime) -> str:
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


# ---- auth -------------------------------------------------------------------

@router.post("/session")
async def admin_login(request: Request, payload: dict = Body(...), db: AsyncSession = Depends(get_async_db)) -> dict:
    """Логин: {username, password} → constant-time проверка → подписанная сессия (Bearer)."""
    # Строгий лимит на логин (отдельно от общего 600/мин) — гасит перебор пароля.
    client = get_redis(decode=True)
    if client is not None:
        fwd = request.headers.get("x-forwarded-for", "")
        ip = fwd.split(",")[0].strip() or (request.client.host if request.client else "?")
        try:
            n = await client.incr(f"rl:admin:login:{ip}")
            if n == 1:
                await client.expire(f"rl:admin:login:{ip}", 60)
            if n > 10:
                raise HTTPException(status_code=429, detail="too many attempts")
        except HTTPException:
            raise
        except Exception:
            pass

    username = validate_credentials(payload.get("username", ""), payload.get("password", ""))
    token, exp = issue_session(username)
    await write_audit(db, request, username, "auth.login", result="ok")
    return {
        "token": token,
        "expires": datetime.fromtimestamp(exp, tz=timezone.utc).isoformat(),
        "user": {"username": username},
    }


@router.get("/me")
async def admin_me(actor: str = Depends(require_admin)) -> dict:
    return {"username": actor}


@router.post("/logout")
async def admin_logout(request: Request, actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db)) -> dict:
    await write_audit(db, request, actor, "auth.logout", result="ok")
    return {"ok": True}


# ---- overview (дашборд) -----------------------------------------------------

@router.get("/overview")
async def admin_overview(actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db)) -> dict:
    out: dict = {"as_of": datetime.now(timezone.utc).isoformat(), "catalog": {}, "users": {}, "north_star": {}, "ingest": []}

    try:
        r = (await db.execute(text(
            "SELECT "
            " count(*) FILTER (WHERE status='active') AS active, "
            " count(*) FILTER (WHERE status='active' AND (cached_image_url IS NOT NULL OR primary_image_url <> '')) AS with_image, "
            " count(*) FILTER (WHERE created_at > now() - interval '24 hours') AS new_24h, "
            " count(*) FILTER (WHERE created_at > now() - interval '7 days') AS new_7d, "
            " count(*) AS total "
            "FROM events.events"
        ))).first()
        venues = (await db.execute(text("SELECT count(*) FROM events.venues"))).scalar()
        # EXISTS, не DISTINCT-джойн: пробы по индексу ix_occurrences_event на ~21к активных событий —
        # секунды → миллисекунды (джойн материализовал сотни тысяч occurrences).
        future = (await db.execute(text(
            "SELECT count(*) FROM events.events e WHERE e.status='active' "
            "AND EXISTS (SELECT 1 FROM events.event_occurrences o "
            "WHERE o.event_id = e.event_id AND o.date_start > now())"
        ))).scalar()
        out["catalog"] = {
            "active": int(r[0] or 0),
            "with_image": int(r[1] or 0),
            "image_share": round((r[1] or 0) / r[0], 3) if r[0] else 0.0,
            "future": int(future or 0),
            "future_share": round((future or 0) / r[0], 3) if r[0] else 0.0,
            "new_24h": int(r[2] or 0),
            "new_7d": int(r[3] or 0),
            "total": int(r[4] or 0),
            "venues": int(venues or 0),
        }
    except Exception:
        pass

    try:
        u = (await db.execute(text(
            "SELECT count(*) total, "
            " count(*) FILTER (WHERE last_active_at > now() - interval '7 days') active_7d, "
            " count(*) FILTER (WHERE created_at > now() - interval '7 days') new_7d, "
            " count(*) FILTER (WHERE notify_digest) digest_optin "
            "FROM ref.users"
        ))).first()
        out["users"] = {"total": int(u[0] or 0), "active_7d": int(u[1] or 0), "new_7d": int(u[2] or 0), "digest_optin": int(u[3] or 0)}
    except Exception:
        pass

    out["north_star"] = await _north_star()
    out["ingest"] = await _ingest_health(db)
    return out


async def _north_star() -> dict:
    """WAU за 4 ISO-недели + суммы действий за 7д из тех же Redis-ключей, что пишет intent.py."""
    now = datetime.now(timezone.utc)
    ns: dict = {"wau": [], "actions_7d": {k: 0 for k in _KINDS}}
    client = get_redis(decode=True)
    if client is None:
        ns["wau"] = [{"week": _isoweek(now - timedelta(weeks=i)), "users": 0} for i in range(_WEEKS_BACK)]
        return ns
    weeks = [_isoweek(now - timedelta(weeks=i)) for i in range(_WEEKS_BACK)]
    try:
        pipe = client.pipeline()
        for w in weeks:
            pipe.scard(f"intent:wau:{w}")
        counts = await pipe.execute()
    except Exception:
        counts = [0] * len(weeks)
    ns["wau"] = [{"week": w, "users": int(n or 0)} for w, n in zip(weeks, counts)]
    days = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(_DAYS_BACK)]
    try:
        pipe = client.pipeline()
        for kind in _KINDS:
            for day in days:
                pipe.get(f"intent:act:{kind}:{day}")
        raw = await pipe.execute()
        per = len(days)
        ns["actions_7d"] = {
            kind: sum(int(v) for v in raw[i * per:(i + 1) * per] if v is not None and str(v).lstrip("-").isdigit())
            for i, kind in enumerate(_KINDS)
        }
    except Exception:
        pass
    return ns


async def _ingest_health(db: AsyncSession) -> list:
    """Здоровье ингеста, СГРУППИРОВАННОЕ по семейству источника (376 per-city источников → ~5 семейств:
    afisha_ru/kudago/telegram_public/timepad/yandex_afisha). Семейство = префикс имени до первого ':'/'-'.
    Для каждого: сколько источников/активных, сколько с успешным последним прогоном, свежесть (мин. лаг)."""
    try:
        rows = (await db.execute(text(
            "SELECT split_part(split_part(s.name, ':', 1), '-', 1) AS family, "
            "  count(*) AS sources, count(*) FILTER (WHERE s.is_active) AS active, "
            "  count(*) FILTER (WHERE r.status='success') AS ok, "
            "  count(*) FILTER (WHERE r.status IS NOT NULL AND r.status NOT IN ('success','running')) AS failed, "
            "  max(r.finished_at) AS latest_finish, "
            "  min(EXTRACT(EPOCH FROM (now() - COALESCE(r.finished_at, r.started_at))) / 3600.0) AS min_lag_h "
            "FROM ref.sources s "
            "LEFT JOIN LATERAL ("
            "  SELECT status, started_at, finished_at FROM events.source_runs sr "
            "  WHERE sr.source_id = s.source_id ORDER BY sr.started_at DESC LIMIT 1"
            ") r ON true GROUP BY family ORDER BY family"
        ))).all()
    except Exception:
        return []
    out = []
    for family, sources, active, ok, failed, latest, min_lag in rows:
        out.append({
            "family": family,
            "sources": int(sources),
            "active": int(active),
            "ok": int(ok),
            "failed": int(failed),
            "latest_finish": latest.isoformat() if latest else None,
            "lag_hours": round(float(min_lag), 1) if min_lag is not None else None,
        })
    return out


# ---- health (инфра) ---------------------------------------------------------

@router.get("/health")
async def admin_health(actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db)) -> dict:
    s = get_settings()
    deps: dict = {"postgres": "down", "redis": "down"}

    try:
        await db.execute(text("SELECT 1"))
        deps["postgres"] = "ok"
    except Exception:
        pass

    client = get_redis(decode=True)
    if client is not None:
        try:
            await client.ping()
            deps["redis"] = "ok"
        except Exception:
            pass

    if s.meili_search_enabled:
        deps["meili"] = "down"
        try:
            async with httpx.AsyncClient(timeout=2.0) as h:
                resp = await h.get(f"{s.meili_url.rstrip('/')}/health")
                deps["meili"] = "ok" if resp.status_code == 200 else "degraded"
        except Exception:
            pass

    stuck = 0
    try:
        stuck = int((await db.execute(text(
            "SELECT count(*) FROM events.source_runs WHERE status='running' AND started_at < now() - interval '2 hours'"
        ))).scalar() or 0)
    except Exception:
        pass

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "deps": deps,
        "stuck_runs": stuck,
        "ingest": await _ingest_health(db),
    }
