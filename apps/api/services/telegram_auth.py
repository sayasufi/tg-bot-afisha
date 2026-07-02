"""Validate Telegram Mini App initData (HMAC-SHA256 signed with the bot token)."""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from fastapi import HTTPException

from core.config.settings import get_settings

# Max age of initData. A valid signature lasts forever otherwise, so a captured
# initData string would be replayable indefinitely; Telegram stamps auth_date for
# exactly this freshness check. 24h covers a normal mini-app session.
_INIT_DATA_MAX_AGE_SECONDS = 24 * 3600


def validate_init_data(init_data: str) -> dict:
    """Return the verified Telegram user dict, or raise HTTPException.

    The signature is checked per Telegram's WebApp spec:
    secret = HMAC_SHA256("WebAppData", bot_token); hash = HMAC_SHA256(secret, data_check_string).
    """
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise HTTPException(status_code=503, detail="bot token is not configured")

    data = dict(parse_qsl(init_data, keep_blank_values=True))
    provided_hash = data.pop("hash", None)
    if not provided_hash:
        raise HTTPException(status_code=400, detail="missing hash")

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hmac.new(b"WebAppData", settings.telegram_bot_token.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, provided_hash):
        raise HTTPException(status_code=401, detail="invalid init data")

    # Only trust auth_date AFTER the signature checks out — then reject stale data
    # so a leaked initData can't be replayed forever.
    try:
        auth_date = int(data.get("auth_date", "0"))
    except (TypeError, ValueError):
        auth_date = 0
    if auth_date <= 0 or time.time() - auth_date > _INIT_DATA_MAX_AGE_SECONDS:
        raise HTTPException(status_code=401, detail="init data expired")

    try:
        return json.loads(data.get("user") or "{}")
    except (ValueError, TypeError):  # malformed user JSON → treat as invalid, not a 500
        raise HTTPException(status_code=401, detail="invalid init data user")
