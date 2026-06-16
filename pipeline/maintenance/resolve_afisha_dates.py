"""Fill in the exact session dates for afisha SPARSE events.

The afisha listing carries only Min/Max + SessionsCount, so a sparse run (a few
discrete shows across weeks) lands as a coarse occurrence. This job fetches the
performance detail page ONCE per such event (`Schedule[].Sessions[].DateTime`) and
rebuilds its occurrences to the real dates, keeping event_id/sources/venue.

Idempotent and bounded:
  * only afisha events with a *sparse* session count (2..6) and fewer stored
    occurrences than sessions (or a multi-day span) are candidates — once resolved
    they match and are skipped, so steady-state cost is just new sparse events;
  * dense runs (many sessions) keep the cheap listing span and are never fetched;
  * at most ``_BATCH`` events per run, so the initial backlog drains over a few
    runs and no single run hammers afisha.

Run:  docker compose -p tg-bot-afisha exec -T prefect-serve python -m pipeline.maintenance.resolve_afisha_dates
"""
import asyncio
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from connectors.web.afisha_ru_connector import AfishaRuConnector
from core.db.session import SessionLocal

_BATCH = 200
_MSK = timezone(timedelta(hours=3))

_CANDIDATES = """
select e.event_id, max(es.source_event_url) as url
from events.events e
join events.event_occurrences o on o.event_id = e.event_id
join events.event_sources es on es.event_id = e.event_id
join ref.sources s on s.source_id = es.source_id
join events.raw_events r on r.raw_id = es.raw_id
where e.status = 'active' and s.name = 'afisha_ru'
  and es.source_event_url like '%afisha.ru/%'
group by e.event_id
having
  -- a leftover [min,max] span renders as a misleading range -> always resolve it,
  bool_or(o.date_end is not null and (o.date_end - o.date_start) > interval '2 days')
  -- or we have fewer discrete dates than the detail can give (capped at 12)
  or ( coalesce(max((r.raw_payload_json->>'sessions_count')::int), 0) >= 2
       and count(distinct o.occurrence_id) < least(coalesce(max((r.raw_payload_json->>'sessions_count')::int), 0), 12) )
limit :lim
"""

_OCCS = "select venue_id, extract(epoch from date_start)::bigint, price_min, price_max, currency, source_best_url from events.event_occurrences where event_id = :e"
_INSERT = ("insert into events.event_occurrences (event_id, venue_id, date_start, date_end, price_min, price_max, currency, source_best_url) "
           "values (:e, :v, :ds, :de, :pmin, :pmax, :cur, :url)")


async def resolve(apply: bool, limit: int = _BATCH) -> dict:
    db = SessionLocal()
    conn = AfishaRuConnector()
    today = datetime.now(_MSK).date()
    fetched = rebuilt = 0
    try:
        cands = db.execute(text(_CANDIDATES), {"lim": limit}).all()
        async with conn._session() as session:
            for eid, url in cands:
                rows = await conn._detail_sessions(session, url, today)
                fetched += 1
                await asyncio.sleep(conn._PAGE_DELAY * 0.4)
                if not rows:
                    continue
                occs = db.execute(text(_OCCS), {"e": str(eid)}).all()
                if not occs:
                    continue
                new_starts = {int(r["start"]) for r in rows}
                if {int(o[1]) for o in occs} == new_starts:
                    continue  # already matches
                venue = Counter(o[0] for o in occs if o[0] is not None).most_common(1)
                venue_id = venue[0][0] if venue else occs[0][0]
                tmpl = next((o for o in occs if o[0] == venue_id), occs[0])
                pmin, pmax, cur, surl = tmpl[2], tmpl[3], tmpl[4], tmpl[5]
                db.execute(text("delete from events.event_occurrences where event_id = :e"), {"e": str(eid)})
                for r in rows:
                    db.execute(text(_INSERT), {
                        "e": str(eid), "v": venue_id,
                        "ds": datetime.fromtimestamp(int(r["start"]), tz=timezone.utc),
                        "de": None, "pmin": pmin, "pmax": pmax, "cur": cur or "RUB", "url": surl or "",
                    })
                rebuilt += 1
        if apply:
            db.commit()
        else:
            db.rollback()
        return {"candidates": len(cands), "fetched": fetched, "rebuilt": rebuilt, "applied": apply}
    finally:
        db.close()


def main(apply: bool) -> None:
    result = asyncio.run(resolve(apply))
    print(("APPLIED" if apply else "DRY RUN (rolled back)") + ": " + str(result))


if __name__ == "__main__":
    main(apply="--dry-run" not in sys.argv)
