"""Веб-аккаунты: регистрация/вход по email+паролю, связка с Telegram.

Зачем: веб-версия и будущие мобильные приложения не могут опираться на Telegram initData.
Сессия — HMAC-токен (services/web_auth), клиент передаёт его в поле init_data с префиксом
``web:`` → все существующие эндпойнты работают без изменений контрактов.

Связка двух миров:
  * веб → TG: POST /link-code выдаёт одноразовый код (Redis, 10 мин) → юзер открывает
    t.me/<bot>?start=link_<code> → бот сливает веб-аккаунт в TG-аккаунт (repositories.accounts).
  * TG → веб: POST /set-credentials (initData-auth) вешает email+пароль на TG-аккаунт —
    после этого вход по email на сайте ведёт в тот же аккаунт.

Сознательно отложено (нет SMTP): подтверждение email и self-serve сброс пароля — сброс пока
через менеджера (@okrest_manager). Пометить в UI.
"""
import secrets

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from apps.api.services.telegram_auth import validate_init_data
from apps.api.services.web_auth import (
    hash_password,
    is_web_uid,
    mint_web_token,
    normalize_email,
    verify_password,
    web_auth_enabled,
)
from core.db.repositories.accounts import create_web_user, find_by_email, set_credentials
from core.db.session import get_async_db
from core.infra.redis import get_redis

router = APIRouter(prefix="/v1/auth", tags=["auth"])

_BOT_USERNAME = "okrestmap_bot"
_LINK_TTL = 600  # одноразовый код связки живёт 10 минут


def _gate() -> None:
    if not web_auth_enabled():
        raise HTTPException(status_code=503, detail="Вход по email пока выключен")


async def _rate_ok(request: Request, bucket: str, limit: int = 10, window: int = 300) -> bool:
    """Анти-брутфорс на вход/регистрацию: N попыток на IP за окно. Redis best-effort — при его
    недоступности пропускаем (scrypt ~50мс сам по себе душит перебор)."""
    client = get_redis(decode=True)
    if client is None:
        return True
    try:
        ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0].strip()
        key = f"webauth:{bucket}:{ip}"
        n = await client.incr(key)
        if n == 1:
            await client.expire(key, window)
        return n <= limit
    except Exception:
        return True


class RegisterRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=8, max_length=128)


@router.post("/register")
async def register(request: Request, payload: RegisterRequest, db: AsyncSession = Depends(get_async_db)) -> dict:
    _gate()
    if not await _rate_ok(request, "reg", limit=5):
        raise HTTPException(status_code=429, detail="Слишком много попыток — попробуй позже")
    email = normalize_email(payload.email)
    if not email:
        raise HTTPException(status_code=422, detail="Некорректный email")
    ph = await run_in_threadpool(hash_password, payload.password)  # scrypt — CPU, не душим event loop
    uid = await create_web_user(db, email, ph)
    if uid is None:
        raise HTTPException(status_code=409, detail="Этот email уже зарегистрирован — войди")
    await db.commit()
    return {"token": mint_web_token(uid), "email": email, "telegram_linked": False}


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=128)


@router.post("/login")
async def login(request: Request, payload: LoginRequest, db: AsyncSession = Depends(get_async_db)) -> dict:
    _gate()
    if not await _rate_ok(request, "login"):
        raise HTTPException(status_code=429, detail="Слишком много попыток — попробуй позже")
    email = normalize_email(payload.email)
    row = await find_by_email(db, email) if email else None
    # verify и на несуществующем юзере (фиктивный хеш) — выравниваем тайминг, не выдаём существование email.
    stored = row[1] if row and row[1] else "scrypt$16384$8$1$00$00"
    ok = await run_in_threadpool(verify_password, payload.password, stored)
    if not (row and ok):
        raise HTTPException(status_code=401, detail="Неверный email или пароль")
    uid = int(row[0])
    return {"token": mint_web_token(uid), "email": email, "telegram_linked": not is_web_uid(uid)}


class TokenRequest(BaseModel):
    init_data: str  # "web:<token>" — тот же транспорт, что у остальных эндпойнтов


@router.post("/me")
async def me(payload: TokenRequest, db: AsyncSession = Depends(get_async_db)) -> dict:
    """Состояние сессии: жива ли, связан ли Telegram (после связки старый web-uid исчезает из БД —
    клиент по exists=false понимает, что пора перелогиниться по email в слитый аккаунт)."""
    user = validate_init_data(payload.init_data)
    uid = int(user.get("id") or 0)
    if not uid:
        raise HTTPException(status_code=401, detail="no user")
    from sqlalchemy import text
    row = (await db.execute(text(
        "SELECT email FROM ref.users WHERE telegram_user_id = :u"), {"u": uid})).first()
    return {
        "user_id": uid,
        "exists": row is not None,
        "email": row[0] if row else None,
        "telegram_linked": not is_web_uid(uid),
    }


@router.post("/link-code")
async def link_code(payload: TokenRequest) -> dict:
    """Одноразовый код связки веб-аккаунта с Telegram. Только для web-сессий (TG-аккаунту связывать
    нечего). Код 10 минут живёт в Redis → бот по /start link_<code> выполняет слияние."""
    _gate()
    user = validate_init_data(payload.init_data)
    uid = int(user.get("id") or 0)
    if not uid or not user.get("web"):
        raise HTTPException(status_code=400, detail="Связка доступна только веб-аккаунту")
    client = get_redis(decode=True)
    if client is None:
        raise HTTPException(status_code=503, detail="Попробуй позже")
    code = secrets.token_urlsafe(12).replace("-", "").replace("_", "")[:16]
    await client.set(f"weblink:{code}", str(uid), ex=_LINK_TTL)
    return {"code": code, "url": f"https://t.me/{_BOT_USERNAME}?start=link_{code}", "ttl": _LINK_TTL}


class SetCredentialsRequest(BaseModel):
    init_data: str  # Telegram initData — вешаем вход на СВОЙ TG-аккаунт
    email: str = Field(max_length=320)
    password: str = Field(min_length=8, max_length=128)


@router.post("/set-credentials")
async def set_creds(request: Request, payload: SetCredentialsRequest, db: AsyncSession = Depends(get_async_db)) -> dict:
    """«Вход на сайте» для TG-юзера: задать email+пароль на свой аккаунт из миниаппа."""
    _gate()
    if not await _rate_ok(request, "setcred", limit=5):
        raise HTTPException(status_code=429, detail="Слишком много попыток — попробуй позже")
    user = validate_init_data(payload.init_data)
    uid = int(user.get("id") or 0)
    if not uid or user.get("web"):
        raise HTTPException(status_code=400, detail="Открой из Telegram")
    email = normalize_email(payload.email)
    if not email:
        raise HTTPException(status_code=422, detail="Некорректный email")
    ph = await run_in_threadpool(hash_password, payload.password)
    if not await set_credentials(db, uid, email, ph):
        raise HTTPException(status_code=409, detail="Этот email уже занят другим аккаунтом")
    await db.commit()
    return {"ok": True, "email": email}
