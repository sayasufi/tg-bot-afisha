"""Admin-панель: вкладка «Дубликаты» — прозрачность дедупа (read-only).

В системе НЕТ хранимой очереди пар-на-ревью: слияния и событий, и площадок автоматические и
необратимые (дубль repointed→canonical→удалён). Классификация «needs-review» (скор 0.72–0.86) — лишь
счётчик прогона, в таблицу не пишется. Поэтому вкладка показывает не очередь, а: действующие пороги
(импортированы из констант-источников, чтобы панель не врала при их перетюне), живые счётчики (включая
near-dup инвариант healthcheck) и точку запуска самоисцеления. require_admin.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.services.admin_auth import require_admin
from core.db.session import get_async_db
from core.matching.scorer import AUTO_MERGE_THRESHOLD, REVIEW_THRESHOLD
from core.matching.title_match import RATIO_AUTO, RATIO_FUZZY
from core.matching.venue_match import COHOST_RATIO, STRONG_RATIO

router = APIRouter(prefix="/v1/admin", tags=["admin"])

# Инвариант healthcheck: одноимённые площадки в пределах 200м (норма 0 — иначе дубль-пины). Один
# индексный запрос (НЕ тяжёлые find_pairs/resplit — те только для prefect-serve по расписанию).
_NEAR_DUP_VENUES = """
with v as (
  select venue_id, regexp_replace(translate(lower(name),'ё','е'),'[^0-9a-zа-я]','','g') nk, geom
  from events.venues where geom is not null and name <> ''
)
select count(*) from v a where exists (
  select 1 from v b where b.venue_id <> a.venue_id and b.nk = a.nk
    and ST_DWithin(a.geom::geography, b.geom::geography, 200))
"""


@router.get("/dedup/status")
async def dedup_status(actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db)) -> dict:
    near_dup = (await db.execute(text(_NEAR_DUP_VENUES))).scalar()
    venues_total = (await db.execute(text("SELECT count(*) FROM events.venues"))).scalar()
    events_active = (await db.execute(text("SELECT count(*) FROM events.events WHERE status='active'"))).scalar()
    multi_occ = (await db.execute(text(
        "SELECT count(*) FROM (SELECT event_id FROM events.event_occurrences "
        "GROUP BY event_id HAVING count(*) > 1) t"
    ))).scalar()
    return {
        "thresholds": {
            "event_auto_merge": AUTO_MERGE_THRESHOLD,
            "event_review": REVIEW_THRESHOLD,
            "title_ratio_auto": RATIO_AUTO,
            "title_ratio_fuzzy": RATIO_FUZZY,
            "venue_strong_ratio": STRONG_RATIO,
            "venue_cohost_ratio": COHOST_RATIO,
            "venue_radius_m": 150,           # source: pipeline/maintenance/venues.py _RADIUS_M
            "venue_show_radius_m": 30,       # source: pipeline/maintenance/venues.py _SHOW_RADIUS_M
            "venue_writetime_fuzzy_m": 200,  # source: core/db/repositories/ingestion.py _VENUE_FUZZY_M
            "venue_writetime_tight_m": 150,  # source: core/db/repositories/ingestion.py _VENUE_TIGHT_M
        },
        "counts": {
            "venues_total": int(venues_total or 0),
            "events_active": int(events_active or 0),
            "near_dup_venues": int(near_dup or 0),
            "events_multi_occurrence": int(multi_occ or 0),
        },
        "self_heal": {"flow": "self-heal-dedup", "interval_s": 900},
    }
