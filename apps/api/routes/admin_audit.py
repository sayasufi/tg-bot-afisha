"""Admin-панель: вкладка «Журнал действий» — лента ref.admin_audit (кто/что/когда менял).

Read-only: каждое мутирующее admin-действие пишется write_audit. Фильтр по типу действия, пагинация 100,
новые сверху. require_admin.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.services.admin_auth import require_admin
from core.db.session import get_async_db

router = APIRouter(prefix="/v1/admin", tags=["admin"])
_PAGE_SIZE = 100


@router.get("/audit/facets")
async def audit_facets(actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db)) -> dict:
    actions = (await db.execute(text("SELECT DISTINCT action FROM ref.admin_audit ORDER BY action"))).scalars().all()
    return {"actions": list(actions)}


@router.get("/audit")
async def list_audit(
    action: str | None = None, page: int = 0,
    actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db),
) -> dict:
    offset = min(max(0, int(page)), 100000) * _PAGE_SIZE
    params = {"action": action, "limit": _PAGE_SIZE, "offset": offset}
    where = "(CAST(:action AS text) IS NULL OR action = :action)"
    total = (await db.execute(text(f"SELECT count(*) FROM ref.admin_audit WHERE {where}"), params)).scalar()
    rows = (await db.execute(text(
        "SELECT actor, action, target, params, result, ip, created_at FROM ref.admin_audit "
        f"WHERE {where} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
    ), params)).mappings().all()
    items = [{
        "actor": m["actor"], "action": m["action"], "target": m["target"],
        "params": m["params"] if isinstance(m["params"], dict) else None,
        "result": m["result"], "ip": m["ip"],
        "created_at": m["created_at"].isoformat() if m["created_at"] else None,
    } for m in rows]
    return {"items": items, "total": int(total or 0), "page": int(page), "page_size": _PAGE_SIZE}
