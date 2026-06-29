"""Admin-панель: «Обработка данных» (воронка пайплайна) и «Бэкапы и сервис» (размер БД/таблиц).

Read-only метрики. Запуск процессов идёт через уже существующий /v1/admin/ops/run (раздел «Процессы»),
сюда не дублируется. require_admin.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.services.admin_auth import require_admin
from core.db.session import get_async_db

router = APIRouter(prefix="/v1/admin", tags=["admin"])


@router.get("/ops/pipeline")
async def pipeline(actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db)) -> dict:
    """Воронка обработки: сырьё → кандидаты → события (+ сессии). Показывает, где данные «застряли»."""
    raw = (await db.execute(text("SELECT count(*) FROM events.raw_events"))).scalar()
    cand = (await db.execute(text("SELECT count(*) FROM events.event_candidates"))).scalar()
    ev_total = (await db.execute(text("SELECT count(*) FROM events.events"))).scalar()
    ev_active = (await db.execute(text("SELECT count(*) FROM events.events WHERE status='active'"))).scalar()
    occ = (await db.execute(text("SELECT count(*) FROM events.event_occurrences"))).scalar()
    runs_total = (await db.execute(text("SELECT count(*) FROM events.source_runs"))).scalar()
    runs_running = (await db.execute(text("SELECT count(*) FROM events.source_runs WHERE status='running'"))).scalar()
    runs_failed_24h = (await db.execute(text(
        "SELECT count(*) FROM events.source_runs WHERE status='failed' AND started_at > now() - interval '24 hours'"))).scalar()
    return {
        "funnel": [
            {"stage": "сырьё (raw)", "n": int(raw or 0)},
            {"stage": "кандидаты", "n": int(cand or 0)},
            {"stage": "события всего", "n": int(ev_total or 0)},
            {"stage": "события активные", "n": int(ev_active or 0)},
            {"stage": "сессии (occurrences)", "n": int(occ or 0)},
        ],
        "runs": {"total": int(runs_total or 0), "running": int(runs_running or 0), "failed_24h": int(runs_failed_24h or 0)},
    }


@router.get("/ops/system")
async def system(actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db)) -> dict:
    """Размер БД и крупнейшие таблицы (для контроля роста / бэкапов). Имена объектов — из каталога PG."""
    db_size = (await db.execute(text("SELECT pg_size_pretty(pg_database_size(current_database()))"))).scalar()
    db_bytes = (await db.execute(text("SELECT pg_database_size(current_database())"))).scalar()
    rows = (await db.execute(text(
        "SELECT schemaname || '.' || relname AS t, pg_size_pretty(pg_total_relation_size(relid)) AS sz, "
        "  pg_total_relation_size(relid) AS bytes, n_live_tup AS rows "
        "FROM pg_stat_user_tables ORDER BY pg_total_relation_size(relid) DESC LIMIT 12"
    ))).all()
    tables = [{"name": r[0], "size": r[1], "bytes": int(r[2] or 0), "rows": int(r[3] or 0)} for r in rows]
    return {"db_size": db_size, "db_bytes": int(db_bytes or 0), "tables": tables}
