import hashlib
import hmac
import json
from urllib.parse import parse_qsl

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.config.settings import get_settings

router = APIRouter(prefix="/v1/telegram", tags=["telegram"])


class InitDataRequest(BaseModel):
    init_data: str


@router.post("/validate")
def validate_init_data(payload: InitDataRequest):
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise HTTPException(status_code=503, detail="bot token is not configured")

    data = dict(parse_qsl(payload.init_data, keep_blank_values=True))
    provided_hash = data.pop("hash", None)
    if not provided_hash:
        raise HTTPException(status_code=400, detail="missing hash")

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hmac.new(b"WebAppData", settings.telegram_bot_token.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calculated_hash, provided_hash):
        raise HTTPException(status_code=401, detail="invalid init data")

    user = json.loads(data.get("user", "{}")) if data.get("user") else {}
    return {"ok": True, "user": user}
