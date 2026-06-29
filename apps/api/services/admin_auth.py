"""Аутентификация админ-панели (admin.okrestmap.ru) — ОДИН владелец, обычный логин/пароль.

Креды в env (ADMIN_USERNAME / ADMIN_PASSWORD), сессия = подписанный Bearer-токен (HMAC по
ADMIN_SESSION_SECRET, в памяти JS → CSRF невозможен). Отзыв всех сессий = ротация ADMIN_SESSION_SECRET
+ рестарт api. ИНВИЗИБЛ: без пароля/секрета ЛЮБОЙ /v1/admin отвечает 404 (как /v1/stats без токена).
"""
import base64
import hashlib
import hmac
import json
import time

from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config.settings import get_settings


def admin_enabled() -> bool:
    """Админ активен только когда заданы И пароль, И секрет подписи. Иначе вся поверхность невидима."""
    s = get_settings()
    return bool(s.admin_password.strip()) and bool(s.admin_session_secret.strip())


def _invisible() -> HTTPException:
    return HTTPException(status_code=404)


def validate_credentials(username: str, password: str) -> str:
    """Constant-time проверка логина+пароля. Возвращает username или бросает 401 (форма покажет «неверно»).
    404 (невидимость) — только если админ вообще не сконфигурён."""
    if not admin_enabled():
        raise _invisible()
    s = get_settings()
    ok_user = hmac.compare_digest((username or "").strip(), s.admin_username.strip())
    ok_pass = hmac.compare_digest(password or "", s.admin_password)
    if not (ok_user and ok_pass):
        raise HTTPException(status_code=401, detail="неверный логин или пароль")
    return s.admin_username.strip()


# ---- Подписанная сессия (stateless HMAC) ------------------------------------

def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64u_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(payload_b64: str) -> str:
    secret = get_settings().admin_session_secret.encode()
    return hmac.new(secret, payload_b64.encode(), hashlib.sha256).hexdigest()


def issue_session(username: str) -> tuple[str, int]:
    """Выдать подписанный токен сессии. Возвращает (token, exp_unix)."""
    now = int(time.time())
    exp = now + get_settings().admin_session_ttl_hours * 3600
    payload = {"sub": username, "iat": now, "exp": exp}
    payload_b64 = _b64u(json.dumps(payload, separators=(",", ":")).encode())
    return f"{payload_b64}.{_sign(payload_b64)}", exp


def _verify_token(token: str) -> dict | None:
    if not token or token.count(".") != 1:
        return None
    payload_b64, sig = token.split(".", 1)
    if not hmac.compare_digest(_sign(payload_b64), sig):
        return None
    try:
        payload = json.loads(_b64u_decode(payload_b64))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload


async def require_admin(request: Request) -> str:
    """Гейт /v1/admin: проверяет Bearer-сессию. Любой провал → 404 (невидимость). Возвращает actor (username)."""
    if not admin_enabled():
        raise _invisible()
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise _invisible()
    payload = _verify_token(auth[7:].strip())
    if not payload or payload.get("sub") != get_settings().admin_username.strip():
        raise _invisible()
    request.state.admin_actor = payload["sub"]
    return payload["sub"]


# ---- Аудит ------------------------------------------------------------------

async def write_audit(
    db: AsyncSession,
    request: Request,
    actor: str,
    action: str,
    *,
    target: str | None = None,
    params: dict | None = None,
    result: str | None = None,
) -> None:
    """Записать админ-действие в ref.admin_audit. Никогда не валит запрос (best-effort)."""
    try:
        fwd = request.headers.get("x-forwarded-for", "")
        ip = fwd.split(",")[0].strip() or (request.client.host if request.client else None)
        await db.execute(
            text(
                "INSERT INTO ref.admin_audit (actor, action, target, params, result, ip, user_agent) "
                "VALUES (:actor, :action, :target, CAST(:params AS jsonb), :result, :ip, :ua)"
            ),
            {
                "actor": actor,
                "action": action,
                "target": target,
                "params": json.dumps(params) if params is not None else None,
                "result": result,
                "ip": ip,
                "ua": (request.headers.get("user-agent") or "")[:500] or None,
            },
        )
        await db.commit()
    except Exception:
        pass
