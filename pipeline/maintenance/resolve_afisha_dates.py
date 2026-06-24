"""Fill exact session dates for afisha events that are NOT on Yandex.

Yandex's GraphQL already returns every session date in bulk (one cheap paginated
feed per city), so the vast majority of events get their full dates for free — see
yandex_afisha_connector. The only gap is events that exist *only* on afisha.ru,
whose listing carries just Min/Max + a count. For those — and only the multi-show,
non-exhibition ones (a few hundred, not the whole feed) — we ask afisha's own
GraphQL API (graph.afisha.ru, one light JSON call per event, no captcha, reachable
straight from the server IP) for the discrete dates and rebuild the occurrences.

Strictly bounded and idempotent: only afisha-only multi-session shows, capped per
run, a short polite delay between calls, and an event already matching its API
dates is skipped. Any fetch failure just leaves the listing Min/Max in place.

Run:  docker compose -p tg-bot-afisha exec -T prefect-serve python -m pipeline.maintenance.resolve_afisha_dates
"""
import asyncio
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from connectors.web.afisha_ru_connector import AfishaRuConnector
from core.db.session import SessionLocal

_BATCH = 150  # events per run — the GraphQL API is light + captcha-free, so we can move faster
_DELAY = 0.4  # polite gap between API calls (seconds)
_MSK = timezone(timedelta(hours=3))
_PLACEHOLDER_VENUE = "Unknown venue"  # see worker enrich: no venue from the source


def _get_or_create_venue(db, name: str, address: str = "") -> int | None:
    """Reuse an existing venue with this name (prefer a geocoded one) or create a
    bare row (no coords — the scheduled backfill_venues_osm geocodes it by name).
    Used to place an event at its real afisha hall instead of the 'Unknown venue'
    centroid. Returns None for a blank name (caller keeps the fallback venue)."""
    name = (name or "").strip()
    if not name:
        return None
    # Match ё/е-insensitively (and prefer a geocoded row) so "Зелёный театр ВДНХ"
    # and "Зеленый театр ВДНХ" reuse ONE venue instead of spawning a duplicate that
    # then gets its own (often wrong) geocode and splits the event list.
    row = db.execute(text(
        "select venue_id from events.venues "
        "where translate(lower(name), 'ё', 'е') = translate(lower(:n), 'ё', 'е') "
        "order by (geom is not null) desc, venue_id limit 1"
    ), {"n": name[:255]}).first()
    if row:
        return row[0]
    return db.execute(text(
        "insert into events.venues (name, address, city, country, geocode_provider, geocode_confidence) "
        "values (:n, :a, 'Москва', 'RU', '', 0) returning venue_id"
    ), {"n": name[:255], "a": (address or "")[:500]}).scalar()

# afisha-ONLY (no Yandex source) multi-session non-exhibition shows that have fewer
# stored dates than the detail can give (capped at 12), or a leftover span.
_CANDIDATES = """
select e.event_id, max(es.source_event_url) as url
from events.events e
join events.event_occurrences o on o.event_id = e.event_id
join events.event_sources es on es.event_id = e.event_id
join ref.sources s on s.source_id = es.source_id
join events.raw_events r on r.raw_id = es.raw_id
left join events.venues vv on vv.venue_id = o.venue_id
where e.status = 'active' and s.name = 'afisha_ru' and e.category <> 'exhibition'
  -- only types with a GraphQL schedule op; /exhibition/ runs are open-ended spans by design
  and (es.source_event_url like '%afisha.ru/performance/%' or es.source_event_url like '%afisha.ru/concert/%')
  -- MOSCOW-ONLY: the schedule filter uses Moscow's City_2 (_AFISHA_CITY_ID), so resolving a
  -- non-Moscow event would drop its sessions or mis-attach Moscow ones. SPb afisha events keep
  -- their listing date span until a per-city resolve (with the SPb city id) is added.
  and lower(coalesce(vv.city, 'москва')) = 'москва'
group by e.event_id
having
  -- a multi-show event whose stored dates are still sparse (missing the middle ones)
  -- AND that Yandex doesn't already cover in bulk
  (
    coalesce(max((r.raw_payload_json->>'sessions_count')::int), 0) > 2
    and count(distinct o.occurrence_id) < least(coalesce(max((r.raw_payload_json->>'sessions_count')::int), 0), 12)
    and not exists (
      select 1 from events.event_sources es2 join ref.sources s2 on s2.source_id = es2.source_id
      where es2.event_id = e.event_id and s2.name = 'yandex_afisha'
    )
  )
  -- OR a leftover span (any session count, any source mix): a show must never render
  -- as a date range, and the GraphQL dates are authoritative
  or bool_or(o.date_end is not null and (o.date_end - o.date_start) > interval '2 days')
  -- OR the event is stuck at the 'Unknown venue' placeholder — the schedule's place
  -- gives its real hall, so recover it off the city-centre pin
  or bool_or(vv.name = '""" + _PLACEHOLDER_VENUE + """')
limit :lim
"""

_OCCS = "select venue_id, extract(epoch from date_start)::bigint, price_min, price_max, currency, source_best_url, extract(epoch from date_end)::bigint from events.event_occurrences where event_id = :e"
_INSERT = ("insert into events.event_occurrences (event_id, venue_id, date_start, date_end, price_min, price_max, currency, source_best_url) "
           "values (:e, :v, :ds, :de, :pmin, :pmax, :cur, :url)")


async def resolve(apply: bool, limit: int = _BATCH) -> dict:
    db = SessionLocal()
    conn = AfishaRuConnector()
    today = datetime.now(_MSK).date()
    fetched = rebuilt = 0
    placeholder_ids = {r[0] for r in db.execute(
        text("select venue_id from events.venues where name = :n"), {"n": _PLACEHOLDER_VENUE}).all()}
    venue_cache: dict[str, int | None] = {}  # place name -> venue_id, within this run
    try:
        cands = db.execute(text(_CANDIDATES), {"lim": limit}).all()
        async with conn._session() as session:
            for eid, url in cands:
                rows = await conn._graphql_schedule(session, url, today)
                fetched += 1
                await asyncio.sleep(_DELAY)  # polite — never burst
                if not rows:
                    continue
                occs = db.execute(text(_OCCS), {"e": str(eid)}).all()
                if not occs:
                    continue
                # A leftover span, or an event stranded at the placeholder venue, must be
                # rebuilt even if the date_starts already match (span range / wrong place).
                has_span = any(o[6] is not None and (o[6] - o[1]) > 172800 for o in occs)
                # Recover off the placeholder only if the schedule actually gives a real
                # place to move to — otherwise rebuilding just re-pins it to the
                # placeholder and it re-qualifies forever (oscillation).
                recoverable = any((r.get("place_name") or "").strip() for r in rows)
                at_placeholder = recoverable and any(o[0] in placeholder_ids for o in occs)
                if not has_span and not at_placeholder and {int(o[1]) for o in occs} == {int(r["start"]) for r in rows}:
                    continue
                # Fallback venue = the event's most common REAL (non-placeholder) venue,
                # used for sessions whose GraphQL place is blank.
                non_ph = [o[0] for o in occs if o[0] is not None and o[0] not in placeholder_ids]
                fallback_vid = Counter(non_ph).most_common(1)[0][0] if non_ph else occs[0][0]
                tmpl = next((o for o in occs if o[0] == fallback_vid), occs[0])
                pmin, pmax, cur, surl = tmpl[2], tmpl[3], tmpl[4], tmpl[5]
                db.execute(text("delete from events.event_occurrences where event_id = :e"), {"e": str(eid)})
                for r in rows:
                    pname = (r.get("place_name") or "").strip()
                    if pname:
                        if pname not in venue_cache:
                            venue_cache[pname] = _get_or_create_venue(db, pname, r.get("place_address", ""))
                        vid = venue_cache[pname] or fallback_vid
                    else:
                        vid = fallback_vid
                    db.execute(text(_INSERT), {
                        "e": str(eid), "v": vid,
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
    print(("APPLIED" if apply else "DRY RUN (rolled back)") + ": " + str(asyncio.run(resolve(apply))))


if __name__ == "__main__":
    main(apply="--dry-run" not in sys.argv)
