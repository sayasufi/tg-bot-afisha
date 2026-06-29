"""Аутентификация админ-панели (admin.okrestmap.ru) — owner-only.

Поток: владелец логинится через Telegram Login Widget на admin-домене → бэкенд проверяет подпись
виджета бот-токеном и что uid в allowlist (ADMIN_TELEGRAM_IDS) → выдаёт подписанную короткую сессию
(HMAC по ADMIN_SESSION_SECRET, с версией-отзыва из ref.users.admin_session_ver). Сессия летит в
заголовке Authorization: Bearer (в памяти JS) — кука не шлётся браузером, поэтому CSRF невозможен.

ИНВИЗИБЛ: если админ не сконфигурён (нет ADMIN_TELEGRAM_IDS или ADMIN_SESSION_SECRET), ЛЮБОЙ /v1/admin
отвечает 404 — поверхность не существует для постороннего, как и /v1/stats без STATS_TOKEN.
"""
import base64
import hashlib
import hmac
import json
import time

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config.settings import get_settings
from core.db.session import get_async_db

# Окно свежести данных Login Widget. Логин обменивается на сессию сразу, поэтому окно короткое —
# перехваченный payload виджета нельзя переиграть позже.
_WIDGET_MAX_AGE_SECONDS = 3600


def admin_ids() -> set[int]:
    raw = get_settings().admin_telegram_ids.strip()
    out: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                out.add(int(part))
            except ValueError:
                continue
    return out


def admin_enabled() -> bool:
    """Админ активен только когда заданы И allowlist, И секрет подписи. Иначе вся поверхность невидима."""
    s = get_settings()
    return bool(admin_ids()) and bool(s.admin_session_secret.strip())


def _invisible() -> HTTPException:
    """404 (не 403) — посторонний не должен даже знать, что /v1/admin существует."""
    return HTTPException(status_code=404)


# ---- Telegram Login Widget --------------------------------------------------

def validate_login_widget(data: dict) -> int:
    """Проверить подпись данных Login Widget и вернуть telegram user id, или бросить 404.

    Подпись виджета (ОТЛИЧАЕТСЯ от Mini App initData): secret = SHA256(bot_token);
    hash = HMAC_SHA256(secret, data_check_string). См. core.telegram спецификацию Login Widget.
    """
    if not admin_enabled():
        raise _invisible()
    token = get_settings().telegram_bot_token
    if not token:
        raise _invisible()

    provided = str(data.get("hash") or "")
    if not provided:
        raise _invisible()
    pairs = {k: v for k, v in data.items() if k != "hash" and v is not None}
    check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hashlib.sha256(token.encode()).digest()
    calculated = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    if not provided.isascii() or not hmac.compare_digest(calculated, provided):
        raise _invisible()

    try:
        auth_date = int(data.get("auth_date", 0))
    except (TypeError, ValueError):
        auth_date = 0
    if auth_date <= 0 or time.time() - auth_date > _WIDGET_MAX_AGE_SECONDS:
        raise _invisible()

    try:
        uid = int(data.get("id"))
    except (TypeError, ValueError):
        raise _invisible()
    if uid not in admin_ids():
        raise _invisible()
    return uid


# ---- Подписанная сессия (stateless HMAC) ------------------------------------

def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64u_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(payload_b64: str) -> str:
    secret = get_settings().admin_session_secret.encode()
    return hmac.new(secret, payload_b64.encode(), hashlib.sha256).hexdigest()


def issue_session(uid: int, ver: int) -> tuple[str, int]:
    """Выдать подписанный токен сессии. Возвращает (token, exp_unix)."""
    now = int(time.time())
    exp = now + get_settings().admin_session_ttl_hours * 3600
    payload = {"uid": uid, "ver": ver, "iat": now, "exp": exp}
    payload_b64 = _b64u(json.dumps(payload, separators=(",", ":")).encode())
    return f"{payload_b64}.{_sign(payload_b64)}", exp


def _verify_token(token: str) -> dict | None:
    """Проверить подпись и срок токена. Возвращает payload или None."""
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


async def _current_session_ver(db: AsyncSession, uid: int) -> int:
    row = (await db.execute(
        text("SELECT admin_session_ver FROM ref.users WHERE telegram_user_id = :uid"), {"uid": uid}
    )).first()
    return int(row[0]) if row else 0


async def require_admin(request: Request, db: AsyncSession = Depends(get_async_db)) -> int:
    """FastAPI-зависимость гейта /v1/admin: проверяет Bearer-сессию + версию-отзыва. Любой провал → 404
    (невидимость). Возвращает actor uid и кладёт его в request.state для аудита."""
    if not admin_enabled():
        raise _invisible()
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise _invisible()
    payload = _verify_token(auth[7:].strip())
    if not payload:
        raise _invisible()
    uid = int(payload.get("uid", 0))
    if uid not in admin_ids():
        raise _invisible()
    if int(payload.get("ver", -1)) != await _current_session_ver(db, uid):
        raise _invisible()  # сессия отозвана (бамп версии)
    request.state.admin_uid = uid
    return uid


async def bump_session_ver(db: AsyncSession, uid: int) -> None:
    """Отозвать все сессии владельца (logout everywhere) — инкремент версии."""
    await db.execute(
        text("UPDATE ref.users SET admin_session_ver = admin_session_ver + 1 WHERE telegram_user_id = :uid"),
        {"uid": uid},
    )
    await db.commit()


# ---- Аудит ------------------------------------------------------------------

async def write_audit(
    db: AsyncSession,
    request: Request,
    actor: int,
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
                "INSERT INTO ref.admin_audit (actor_telegram_id, action, target, params, result, ip, user_agent) "
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
    except Exception:  # аудит не должен ронять операцию
        pass
