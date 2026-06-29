"""Admin live-config: выставляемые настройки, действующие БЕЗ рестарта.

GET    /v1/admin/settings        — список выставляемых настроек + effective-значение + источник.
POST   /v1/admin/settings/{key}  — записать override в ref.app_settings, сбросить кэш, аудит.
DELETE /v1/admin/settings/{key}  — удалить override (вернуть значение из env).

Жёсткий whitelist `_REGISTRY`: писать можно ТОЛЬКО перечисленные ключи, строго проверяя тип. Любой
override отдаётся через слой get_effective (in-proc кэш 15с, гард типа на чтении, fail-open к env).
Выставлены только настройки, читаемые из async-кода (см. core/config/effective.py).
"""
import json

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.services.admin_auth import require_admin, write_audit
from core.config.effective import bust
from core.config.settings import get_settings
from core.db.session import get_async_db

router = APIRouter(prefix="/v1/admin", tags=["admin"])

# key -> (type, RU-метка, RU-группа, RU-подсказка). Дефолт берётся живьём из get_settings().
_REGISTRY: dict[str, tuple[type, str, str, str]] = {
    "meili_search_enabled": (
        bool, "Поиск через Meilisearch", "Поиск",
        "Опечатко-устойчивый поиск. При выключении — обычный поиск Postgres (не ломается, просто строже).",
    ),
    "afisha_enabled": (
        bool, "Сбор Afisha.ru", "Источники",
        "Общий выключатель источника afisha.ru. ВЫКЛ полностью останавливает сбор из него по всем городам.",
    ),
}


def _env_default(key: str):
    return getattr(get_settings(), key)


def _validate(typ: type, value) -> None:
    """Строгая проверка типа значения (B3-фикс: явные ветки, без багов приоритета операторов)."""
    if typ is bool:
        if not isinstance(value, bool):
            raise HTTPException(status_code=422, detail="значение должно быть да/нет (boolean)")
    elif typ is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise HTTPException(status_code=422, detail="значение должно быть целым числом")
    elif typ is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise HTTPException(status_code=422, detail="значение должно быть числом")


@router.get("/settings")
async def list_settings(_: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db)) -> dict:
    rows = (await db.execute(text("SELECT key, value FROM ref.app_settings"))).all()
    overrides = {k: v for k, v in rows}
    items = []
    for key, (typ, label, group, hint) in _REGISTRY.items():
        default = _env_default(key)
        overridden = key in overrides
        items.append({
            "key": key,
            "type": typ.__name__,
            "label": label,
            "group": group,
            "hint": hint,
            "default": default,
            "value": overrides[key] if overridden else default,
            "source": "override" if overridden else "env",
        })
    return {"items": items}


@router.post("/settings/{key}")
async def set_setting(
    key: str,
    request: Request,
    payload: dict = Body(...),
    actor: str = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    if key not in _REGISTRY:
        raise HTTPException(status_code=404, detail="неизвестная настройка")
    typ = _REGISTRY[key][0]
    value = payload.get("value")
    _validate(typ, value)
    await db.execute(
        text(
            "INSERT INTO ref.app_settings (key, value, updated_at) "
            "VALUES (:k, CAST(:v AS jsonb), now()) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()"
        ),
        {"k": key, "v": json.dumps(value)},
    )
    await db.commit()
    bust(key)  # записавший процесс свеж мгновенно; остальные — за TTL (≤15с)
    await write_audit(db, request, actor, "settings.update", target=key, params={"value": value}, result="ok")
    return {"key": key, "value": value, "source": "override"}


@router.delete("/settings/{key}")
async def reset_setting(
    key: str,
    request: Request,
    actor: str = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    if key not in _REGISTRY:
        raise HTTPException(status_code=404, detail="неизвестная настройка")
    await db.execute(text("DELETE FROM ref.app_settings WHERE key = :k"), {"k": key})
    await db.commit()
    bust(key)
    await write_audit(db, request, actor, "settings.reset", target=key, result="ok")
    return {"key": key, "value": _env_default(key), "source": "env"}
