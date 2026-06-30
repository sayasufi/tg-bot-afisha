"""Admin: дашборд ВОРОНКИ и УДЕРЖАНИЯ — чтобы видеть, работают ли ретеншн-фиксы и окупается ли реклама.

Источник → открыл апп → онбординг → город → сохранил (intent) → вернулся; когорты по неделе входа с
D1/D7/D30-удержанием (прокси: last_app_open_at − created_at ≥ N дней, знаменатель = «дозревшие»); разбивка
по источнику привлечения; тренд новых/сохранений; счётчики возвратных петель. Всё из ref.users + favorites.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.services.admin_auth import require_admin
from core.db.session import get_async_db

router = APIRouter(prefix="/v1/admin", tags=["admin"])

_FAV = "EXISTS (SELECT 1 FROM ref.user_favorites f WHERE f.telegram_user_id = u.telegram_user_id)"


def _pct(n, d):
    return round(n / d * 100, 1) if d else None


@router.get("/funnel")
async def funnel(actor: str = Depends(require_admin), db: AsyncSession = Depends(get_async_db)) -> dict:
    f = (await db.execute(text(
        "SELECT count(*) total, "
        "  count(*) FILTER (WHERE acq_source IS NOT NULL) attributed, "
        "  count(*) FILTER (WHERE last_app_open_at IS NOT NULL) opened, "
        "  count(*) FILTER (WHERE onboarded) onboarded, "
        "  count(*) FILTER (WHERE city_slug IS NOT NULL AND city_slug <> '') city, "
        f"  count(*) FILTER (WHERE {_FAV}) saved, "
        "  count(*) FILTER (WHERE last_app_open_at > created_at + interval '2 days') returned "
        "FROM ref.users u"
    ))).first()
    total = int(f[0] or 0)
    funnel_stages = [
        {"stage": "Пришли (всего)", "n": total},
        {"stage": "Открыли приложение", "n": int(f[2] or 0)},
        {"stage": "Прошли онбординг", "n": int(f[3] or 0)},
        {"stage": "Указали город", "n": int(f[4] or 0)},
        {"stage": "Сохранили событие", "n": int(f[5] or 0)},
        {"stage": "Вернулись (2+ дня)", "n": int(f[6] or 0)},
    ]
    for s in funnel_stages:
        s["pct"] = _pct(s["n"], total)

    cohort_rows = (await db.execute(text(
        "SELECT date_trunc('week', created_at)::date wk, count(*) sz, "
        "  count(*) FILTER (WHERE created_at <= now() - interval '1 day') m1, "
        "  count(*) FILTER (WHERE last_app_open_at >= created_at + interval '1 day') r1, "
        "  count(*) FILTER (WHERE created_at <= now() - interval '7 days') m7, "
        "  count(*) FILTER (WHERE last_app_open_at >= created_at + interval '7 days') r7, "
        "  count(*) FILTER (WHERE created_at <= now() - interval '30 days') m30, "
        "  count(*) FILTER (WHERE last_app_open_at >= created_at + interval '30 days') r30 "
        "FROM ref.users GROUP BY 1 ORDER BY 1 DESC LIMIT 12"
    ))).all()
    cohorts = [{
        "week": r[0].isoformat(), "size": int(r[1] or 0),
        "d1": _pct(int(r[3] or 0), int(r[2] or 0)),
        "d7": _pct(int(r[5] or 0), int(r[4] or 0)),
        "d30": _pct(int(r[7] or 0), int(r[6] or 0)),
    } for r in cohort_rows]

    src_rows = (await db.execute(text(
        "SELECT acq_source, count(*) came, "
        "  count(*) FILTER (WHERE last_app_open_at IS NOT NULL) opened, "
        f"  count(*) FILTER (WHERE {_FAV}) saved, "
        "  count(*) FILTER (WHERE last_app_open_at > created_at + interval '2 days') returned "
        "FROM ref.users u WHERE acq_source IS NOT NULL GROUP BY acq_source ORDER BY came DESC LIMIT 30"
    ))).all()
    by_source = [{
        "source": r[0], "came": int(r[1] or 0), "opened": int(r[2] or 0),
        "saved": int(r[3] or 0), "returned": int(r[4] or 0),
        "save_rate": _pct(int(r[3] or 0), int(r[1] or 0)),
    } for r in src_rows]

    # Тренд 30 дней: новые юзеры + сохранения по дням → один список по дате.
    new_rows = dict((r[0].isoformat(), int(r[1])) for r in (await db.execute(text(
        "SELECT created_at::date d, count(*) FROM ref.users WHERE created_at > now() - interval '30 days' GROUP BY 1"
    ))).all())
    sav_rows = dict((r[0].isoformat(), int(r[1])) for r in (await db.execute(text(
        "SELECT created_at::date d, count(*) FROM ref.user_favorites WHERE created_at > now() - interval '30 days' GROUP BY 1"
    ))).all())
    days = sorted(set(new_rows) | set(sav_rows))
    trend = [{"day": d, "new": new_rows.get(d, 0), "saves": sav_rows.get(d, 0)} for d in days]

    loops = (await db.execute(text(
        "SELECT count(*) FILTER (WHERE last_digest_sent_at IS NOT NULL) digest, "
        "  count(*) FILTER (WHERE welcome_nudge_at IS NOT NULL) nudge FROM ref.users"
    ))).first()
    total_saves = (await db.execute(text("SELECT count(*) FROM ref.user_favorites"))).scalar()

    return {
        "funnel": funnel_stages,
        "attributed": int(f[1] or 0),
        "organic": total - int(f[1] or 0),
        "retention": {
            "d1": cohorts[0]["d1"] if cohorts else None,  # сводно по самой свежей когорте — детали в таблице
        },
        "cohorts": cohorts,
        "by_source": by_source,
        "trend": trend,
        "loops": {"digest_sent": int(loops[0] or 0), "welcome_nudge": int(loops[1] or 0), "total_saves": int(total_saves or 0)},
    }
