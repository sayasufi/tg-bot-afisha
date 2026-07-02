"""Веб-аккаунты: пароли (scrypt из stdlib — без новых зависимостей) + подписанные сессии.

Токен зеркалит проверенный паттерн admin_auth: base64url(JSON {uid, iat, exp}) + HMAC-SHA256
на WEB_SESSION_SECRET. Клиент передаёт его В ТОМ ЖЕ поле, что Telegram initData, с префиксом
``web:`` — так ОДНА ветка в validate_init_data открывает все существующие эндпойнты
(избранное/настройки/друзья/заявки) для веб-сессий без переделки контрактов.

WEB_ID_FLOOR: чистые веб-аккаунты живут на синтетических id ≥ 10^15 (ref.web_user_id_seq) —
реальные Telegram-id на порядки ниже, коллизии невозможны. id < floor означает «связан с TG».
"""
import base64
import hashlib
import hmac
import json
import os
import re
import time

from core.config.settings import get_settings

WEB_ID_FLOOR = 1_000_000_000_000_000  # 10^15 — синтетические id веб-аккаунтов начинаются отсюда
_TOKEN_TTL = 90 * 24 * 3600  # 90 дней — веб/приложения живут дольше, чем админ-сессия
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")

# scrypt-параметры: n=2^14 — ~50мс на хеш (достаточно против брутфорса, не душит event loop
# через run_in_threadpool). Формат хранения: scrypt$n$r$p$salt_hex$hash_hex — самоописываемый,
# параметры можно поднять в будущем без ломки старых хешей.
_N, _R, _P = 16384, 8, 1


def is_web_uid(uid: int) -> bool:
    """True для синтетического (не связанного с Telegram) веб-аккаунта."""
    return uid >= WEB_ID_FLOOR


def normalize_email(raw: str) -> str | None:
    e = (raw or "").strip().lower()
    return e if e and len(e) <= 320 and _EMAIL_RE.match(e) else None


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${h.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_hex, hash_hex = (stored or "").split("$")
        if algo != "scrypt":
            return False
        h = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex),
                           n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(h.hex(), hash_hex)
    except Exception:
        return False


def _secret() -> bytes:
    return (get_settings().web_session_secret or "").encode()


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(payload_b64: str) -> str:
    return hmac.new(_secret(), payload_b64.encode(), hashlib.sha256).hexdigest()


def web_auth_enabled() -> bool:
    return bool(get_settings().web_session_secret.strip())


def mint_web_token(uid: int) -> str:
    now = int(time.time())
    payload_b64 = _b64u(json.dumps({"uid": int(uid), "iat": now, "exp": now + _TOKEN_TTL},
                                   separators=(",", ":")).encode())
    return f"{payload_b64}.{_sign(payload_b64)}"


def verify_web_token(token: str) -> int | None:
    """uid из валидного токена, иначе None. Токен переживает связку с TG до истечения — после
    merge синтетический uid удалён из БД, эндпойнты вернут пустые данные и клиент разлогинит."""
    if not web_auth_enabled() or not token or token.count(".") != 1:
        return None
    payload_b64, sig = token.split(".", 1)
    if not hmac.compare_digest(_sign(payload_b64), sig):
        return None
    try:
        payload = json.loads(_b64u_dec(payload_b64))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return int(payload["uid"])
    except Exception:
        return None
