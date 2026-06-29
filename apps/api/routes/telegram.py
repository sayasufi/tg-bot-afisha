from fastapi import APIRouter
from pydantic import BaseModel

from apps.api.services.telegram_auth import validate_init_data

router = APIRouter(prefix="/v1/telegram", tags=["telegram"])


class InitDataRequest(BaseModel):
    init_data: str


@router.post("/validate")
def validate(payload: InitDataRequest):
    user = validate_init_data(payload.init_data)
    return {"ok": True, "user": user}
