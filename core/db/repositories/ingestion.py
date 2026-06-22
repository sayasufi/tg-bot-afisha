import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from core.db.models import (
    Event,
    EventCandidate,
    EventOccurrence,
    EventSource,
    RawEvent,
    Source,
    SourceRun,
    TelegramChannel,
    Venue,
)
from pipeline.dedup.scorer import MatchDecision
from pipeline.dedup.title_match import same_event, same_slot_title, title_nkey, translit_tokens
from pipeline.dedup.venue_match import name_match_score
from pipeline.normalizer.extractors import NormalizedCandidate

# Sources list events up to ~a year ahead; a short window dropped every session of
# a far-future event, after which the dedup used to fall back to "now" and the
# event surfaced as happening today (see dedup_and_upsert_event).
_OCCURRENCE_LOOKAHEAD_DAYS = 365
# Max discrete sessions stored per event. MUST match the connectors' _DATES_CAP and
# resolve_afisha_dates' cap (all 12) — otherwise the write path silently drops the
# tail dates a source took care to fetch (e.g. a play's 12 dates collapse to 8).
_OCCURRENCE_CAP = 12
# Moscow is a fixed UTC+3 — "same day" for dedup must be a Moscow calendar day, not a
# UTC one (an all-day MSK-midnight event is stored as the previous UTC day).
_MSK = timezone(timedelta(hours=3))


def _ts_to_dt(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _iso_dt(value: object) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _payload_session_dates(payload: object, now: datetime, until: datetime) -> list[tuple[datetime, datetime | None]]:
    """All in-window sessions from a source payload's ``dates`` rows (unix start/end),
    so one source event with several showtimes becomes several occurrences. Returns
    [] for payloads without ``dates`` (LLM/ldjson sources keep the single primary)."""
    rows = payload.get("dates") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        # Timepad: ISO startDate/endDate IS the authoritative session (no unix `dates` rows). The
        # `iso_dates` marker scopes this to Timepad so LLM/ldjson startDates aren't treated as prunable
        # truth (their re-extraction can drift) — and so prune can actually clean Timepad's stale dates.
        if isinstance(payload, dict) and payload.get("iso_dates"):
            start = _iso_dt(payload.get("startDate"))
            end = _iso_dt(payload.get("endDate"))
            if start is not None and ((now <= start <= until) or (end is not None and start < now <= end)):
                return [(start, end)]
        return []
    out: list[tuple[datetime, datetime | None]] = []
    seen: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        start = _ts_to_dt(row.get("start"))
        if not start:
            continue
        end = _ts_to_dt(row.get("end"))
        in_window = (now <= start <= until) or (end is not None and start < now <= end)
        if not in_window:
            continue
        key = int(start.timestamp())
        if key in seen:
            continue
        seen.add(key)
        out.append((start, end))
    out.sort(key=lambda pair: pair[0])
    return out[:_OCCURRENCE_CAP]


async def get_active_sources(db: AsyncSession) -> list[Source]:
    return list((await db.execute(select(Source).where(Source.is_active.is_(True)))).scalars().all())


async def get_source_by_name(db: AsyncSession, name: str) -> Source | None:
    return (await db.execute(select(Source).where(Source.name == name))).scalar_one_or_none()


async def get_active_telegram_channels(db: AsyncSession) -> list[TelegramChannel]:
    stmt = select(TelegramChannel).where(TelegramChannel.is_active.is_(True)).order_by(TelegramChannel.channel_id.asc())
    return list((await db.execute(stmt)).scalars().all())


async def ensure_source(db: AsyncSession, name: str, kind: str, base_url: str, config_json: dict | None = None) -> Source:
    source = await get_source_by_name(db, name)
    if source:
        return source
    source = Source(name=name, kind=kind, base_url=base_url, config_json=config_json or {})
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


async def create_source_run(db: AsyncSession, source_id: int) -> SourceRun:
    run = SourceRun(source_id=source_id, status="running", started_at=datetime.now(timezone.utc))
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def finish_source_run(db: AsyncSession, run: SourceRun, status: str, stats: dict, error_text: str = "") -> None:
    run.status = status
    run.finished_at = datetime.now(timezone.utc)
    run.stats_json = stats
    run.error_text = error_text
    db.add(run)
    await db.commit()


async def upsert_raw_event(db: AsyncSession, source_id: int, external_id: str, payload: dict, raw_text: str) -> RawEvent:
    # Atomic INSERT ... ON CONFLICT DO UPDATE on (source_id, external_id): avoids the
    # SELECT-then-INSERT race when several workers ingest the same event concurrently.
    # skip_reason is reopened ('') only when the content actually changed.
    content_hash = hashlib.sha256(raw_text.encode("utf-8", errors="ignore")).hexdigest()
    stmt = pg_insert(RawEvent).values(
        source_id=source_id,
        external_id=external_id,
        raw_payload_json=payload,
        raw_text=raw_text,
        content_hash=content_hash,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_raw_source_external",
        set_={
            "raw_payload_json": stmt.excluded.raw_payload_json,
            "raw_text": stmt.excluded.raw_text,
            "content_hash": stmt.excluded.content_hash,
            "skip_reason": case(
                (RawEvent.content_hash != stmt.excluded.content_hash, ""),
                else_=RawEvent.skip_reason,
            ),
        },
    ).returning(RawEvent)
    row = (await db.execute(stmt, execution_options={"populate_existing": True})).scalar_one()
    await db.commit()
    return row


async def bulk_upsert_raw_events(db: AsyncSession, source_id: int, records: list) -> int:
    """Upsert many RawRecords in ONE statement + ONE commit (vs. a commit per row).
    Each record has .external_id/.payload/.raw_text. Returns the number of rows sent."""
    if not records:
        return 0
    # De-dup within the batch (Postgres rejects ON CONFLICT touching a row twice);
    # the last occurrence of an external_id wins.
    by_ext: dict[str, dict] = {}
    for rec in records:
        by_ext[str(rec.external_id)] = {
            "source_id": source_id,
            "external_id": str(rec.external_id),
            "raw_payload_json": rec.payload,
            "raw_text": rec.raw_text,
            "content_hash": hashlib.sha256((rec.raw_text or "").encode("utf-8", "ignore")).hexdigest(),
        }
    rows = list(by_ext.values())
    stmt = pg_insert(RawEvent).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_raw_source_external",
        set_={
            "raw_payload_json": stmt.excluded.raw_payload_json,
            "raw_text": stmt.excluded.raw_text,
            "content_hash": stmt.excluded.content_hash,
            "skip_reason": case(
                (RawEvent.content_hash != stmt.excluded.content_hash, ""),
                else_=RawEvent.skip_reason,
            ),
        },
    )
    await db.execute(stmt)
    await db.commit()
    return len(rows)


async def save_candidate(db: AsyncSession, raw_id: int, candidate: NormalizedCandidate) -> EventCandidate:
    row = EventCandidate(
        raw_id=raw_id,
        title=candidate.title,
        description=candidate.description,
        date_start=candidate.date_start,
        date_end=candidate.date_end,
        venue=candidate.venue,
        address=candidate.address,
        price_min=candidate.price_min,
        price_max=candidate.price_max,
        currency=candidate.currency,
        age_limit=candidate.age_limit,
        tags_json=candidate.tags,
        images_json=candidate.images,
        source_url=candidate.source_url,
        parse_confidence=candidate.parse_confidence,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def unprocessed_raw_ids(db: AsyncSession, limit: int = 100) -> list[int]:
    stmt = (
        select(RawEvent.raw_id)
        .outerjoin(EventCandidate, EventCandidate.raw_id == RawEvent.raw_id)
        .where(EventCandidate.candidate_id.is_(None))
        .where(RawEvent.skip_reason == "")
        .order_by(RawEvent.raw_id.asc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


async def mark_raw_skipped(db: AsyncSession, raw: RawEvent, reason: str) -> None:
    raw.skip_reason = (reason or "skipped")[:64]
    db.add(raw)
    await db.commit()


async def unresolved_candidate_ids(db: AsyncSession, limit: int = 100) -> list[int]:
    stmt = (
        select(EventCandidate.candidate_id)
        .outerjoin(EventSource, EventSource.raw_id == EventCandidate.raw_id)
        .where(EventSource.id.is_(None))
        .where(EventCandidate.venue_id.is_(None))
        .order_by(EventCandidate.candidate_id.asc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_candidate(db: AsyncSession, candidate_id: int) -> EventCandidate | None:
    return await db.get(EventCandidate, candidate_id)


async def get_raw(db: AsyncSession, raw_id: int) -> RawEvent | None:
    # Eager-load the source: normalize/enrich read raw.source.* and async sessions
    # do NOT support lazy relationship loading (would raise MissingGreenlet).
    stmt = select(RawEvent).options(joinedload(RawEvent.source)).where(RawEvent.raw_id == raw_id)
    return (await db.execute(stmt)).scalar_one_or_none()


# Normalise a venue name to a comparison key: lowercase, ё→е, strip everything
# but letters/digits. So "Зелёный театр ВДНХ", "Зеленый театр ВДНХ" and
# "Зелёный театр, ВДНХ" all collapse to one key.
_VENUE_NKEY = "regexp_replace(translate(lower({col}), 'ё', 'е'), '[^0-9a-zа-я]', '', 'g')"
_VENUE_FUZZY_M = 200  # metres — same-named venues this close are the same place
_VENUE_TIGHT_M = 150  # metres — radius for the name-*variant* reuse below


async def get_or_create_venue(db: AsyncSession, name: str, address: str, city: str, country: str, lat: float | None, lon: float | None, provider: str, confidence: float) -> Venue:
    venue = (await db.execute(select(Venue).where(and_(Venue.name == name, Venue.address == address)))).scalar_one_or_none()
    if venue:
        return venue
    # Fuzzy de-dup: an existing geocoded venue with the SAME normalised name within
    # ~200 m is the same physical place — reuse it. Without this, cross-source
    # name/address/coord drift (KudaGo vs Yandex vs Afisha all geocode "Зелёный
    # театр ВДНХ" slightly differently) spawns a venue per source, which then
    # splits one event into a pin per venue. Exact (name,address) is the fast path
    # above; this catches the near-misses.
    if lat is not None and lon is not None:
        match_id = (await db.execute(
            text(
                "SELECT venue_id FROM events.venues "
                "WHERE geom IS NOT NULL "
                "  AND " + _VENUE_NKEY.format(col="name") + " = " + _VENUE_NKEY.format(col=":name") + " "
                "  AND ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :m) "
                "ORDER BY ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) "
                "LIMIT 1"
            ),
            {"name": name or "", "lat": lat, "lon": lon, "m": _VENUE_FUZZY_M},
        )).scalar()
        if match_id is not None:
            return await db.get(Venue, match_id)
        # Name-*variant* de-dup: the exact-key match above misses cross-source
        # naming drift ("Космос" vs "Большой концертный зал «Космос»", "МХТ им.
        # Чехова" vs "МХТ имени А. П. Чехова"). Score the few venues within ~150 m
        # and reuse one whose name is a strong/structural match. Antonym-aware, so
        # Большой/Малый зал of one building stay distinct. (See merge_venues_fuzzy
        # for the one-off cleanup of pre-existing duplicates.)
        nearby = (await db.execute(
            text(
                "SELECT venue_id, name FROM events.venues "
                "WHERE geom IS NOT NULL AND name <> '' "
                "  AND ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :m) "
                "ORDER BY ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) "
                "LIMIT 20"
            ),
            {"lat": lat, "lon": lon, "m": _VENUE_TIGHT_M},
        )).all()
        best_id, best_score = None, 0.0
        for vid, vname in nearby:
            score = name_match_score(name or "", vname or "")
            if score is not None and score > best_score:
                best_id, best_score = vid, score
        if best_id is not None:
            return await db.get(Venue, best_id)
    # Race-safe create: enrich and backfill_venues_osm can both reach the same
    # (name, address) concurrently. INSERT ... ON CONFLICT DO NOTHING + re-select
    # avoids the UniqueViolation on uq_venue_name_address.
    values: dict = {
        "name": name,
        "address": address,
        "city": city,
        "country": country,
        "geocode_provider": provider,
        "geocode_confidence": confidence,
    }
    if lat is not None and lon is not None:
        values["geom"] = func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)
    stmt = pg_insert(Venue).values(**values).on_conflict_do_nothing(constraint="uq_venue_name_address").returning(Venue.venue_id)
    venue_id = (await db.execute(stmt)).scalar_one_or_none()
    await db.commit()
    if venue_id is None:  # another worker inserted it first
        return (await db.execute(select(Venue).where(and_(Venue.name == name, Venue.address == address)))).scalar_one()
    return await db.get(Venue, venue_id)


async def find_cached_venue(db: AsyncSession, name: str, city: str, country: str) -> Venue | None:
    normalized_name = (name or "").strip()
    normalized_city = (city or "").strip()
    normalized_country = (country or "").strip()
    if not normalized_name:
        return None
    stmt = select(Venue).where(
        and_(
            func.lower(Venue.name) == normalized_name.lower(),
            func.lower(Venue.city) == normalized_city.lower(),
            func.lower(Venue.country) == normalized_country.lower(),
            Venue.address != "",
            Venue.geom.is_not(None),
        )
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def unresolved_venue_ids(db: AsyncSession, limit: int = 200) -> list[int]:
    stmt = (
        select(Venue.venue_id)
        .where(
            and_(
                Venue.name != "",
                or_(Venue.address == "", Venue.geom.is_(None)),
            )
        )
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_venue(db: AsyncSession, venue_id: int) -> Venue | None:
    return await db.get(Venue, venue_id)


async def _upsert_occurrences(db: AsyncSession, event: Event, candidate: EventCandidate, venue: Venue | None, raw_id: int) -> None:
    """Upsert this raw's sessions onto the event, idempotent on (event_id, date_start, venue_id): an
    event with several showtimes becomes several occurrences. Sources without a `dates` list keep
    their single primary date; NEVER fall back to now() (that stamps a future event as 'today'); no
    date at all → no occurrence. Run on BOTH first ingest AND re-ingest, so a changed raw (added
    sessions / shifted time / new price) propagates to an existing event instead of freezing forever."""
    raw = await get_raw(db, raw_id)
    now = datetime.now(timezone.utc)
    until = now + timedelta(days=_OCCURRENCE_LOOKAHEAD_DAYS)
    sessions = _payload_session_dates(raw.raw_payload_json if raw else None, now, until)
    if not sessions and candidate.date_start:
        sessions = [(candidate.date_start, candidate.date_end)]
    occ_venue_id = venue.venue_id if venue else None
    for occ_start, occ_end in sessions:
        ins = pg_insert(EventOccurrence).values(
            event_id=event.event_id, venue_id=occ_venue_id, date_start=occ_start, date_end=occ_end,
            price_min=candidate.price_min, price_max=candidate.price_max, currency=candidate.currency,
            source_best_url=candidate.source_url, last_seen_at=now,
        )
        # Single idempotent UPSERT on (event_id, date_start, COALESCE(venue_id,-1)) — race-proof (no
        # duplicate-key) for multi-source events touching the same session. Price rule: take the incoming
        # price ONLY when it's a REAL (non-zero) quote, so a free/unknown source can never overwrite a
        # known paid price (the multi-source «бесплатно» bug). Always refresh last_seen for stale-pruning.
        take_price = func.coalesce(ins.excluded.price_min, 0) > 0
        await db.execute(ins.on_conflict_do_update(
            index_elements=[EventOccurrence.event_id, EventOccurrence.date_start, text("coalesce(venue_id, -1)")],
            set_={
                "date_end": ins.excluded.date_end,
                "price_min": case((take_price, ins.excluded.price_min), else_=EventOccurrence.price_min),
                "price_max": case((take_price, ins.excluded.price_max), else_=EventOccurrence.price_max),
                "currency": case((take_price, ins.excluded.currency), else_=EventOccurrence.currency),
                "source_best_url": ins.excluded.source_best_url,
                "last_seen_at": ins.excluded.last_seen_at,
            },
        ))
    await db.flush()


# --- reprocess CHANGED raws -----------------------------------------------------------
# Raws are normalized ONCE (unprocessed_raw_ids requires candidate_id IS NULL). When a structured
# source UPDATES a raw (dates shift as old ones pass, a price appears, sessions are added), the
# candidate + occurrences would otherwise freeze at first-ingest. These re-normalize the changed raw
# and propagate the fresh date/price through the SAME _upsert_occurrences the first ingest uses.
_STRUCTURED_SOURCES = ("yandex_afisha", "afisha_ru", "kudago", "timepad")


async def stale_structured_raw_ids(db: AsyncSession, limit: int = 200) -> list[int]:
    """Raws whose content changed since the candidate was built (content_hash <> processed_hash, or
    never stamped) — STRUCTURED sources only (rule-based re-normalization is cheap + deterministic, no
    LLM), that already resolved into an event. Ordered, bounded."""
    stmt = (
        select(RawEvent.raw_id)
        .join(Source, Source.source_id == RawEvent.source_id)
        .join(EventCandidate, EventCandidate.raw_id == RawEvent.raw_id)
        .join(EventSource, EventSource.raw_id == RawEvent.raw_id)
        .where(Source.name.in_(_STRUCTURED_SOURCES))
        .where(or_(RawEvent.processed_hash.is_(None), RawEvent.processed_hash != RawEvent.content_hash))
        .order_by(RawEvent.raw_id.asc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().unique().all())


async def reprocess_raw(db: AsyncSession, raw_id: int, normalizer) -> str:
    """Re-normalize ONE changed raw and propagate the fresh date/price onto its candidate + the linked
    event's occurrences — the missing re-ingest trigger. Returns 'refreshed' | 'stamped' (nothing to
    do). ALWAYS stamps processed_hash so a raw is never reprocessed in a tight loop."""
    raw = await get_raw(db, raw_id)
    if raw is None:
        return "stamped"
    fresh = next(iter(normalizer.normalize(raw.raw_payload_json, raw.raw_text)), None)
    cand = (await db.execute(
        select(EventCandidate).where(EventCandidate.raw_id == raw_id).order_by(EventCandidate.candidate_id.asc())
    )).scalars().first()
    if fresh is None or cand is None:
        raw.processed_hash = raw.content_hash
        return "stamped"
    # Refresh the drift-prone fields on the EXISTING candidate (keep its resolved venue_id / category).
    cand.date_start = fresh.date_start
    cand.date_end = fresh.date_end
    cand.price_min = fresh.price_min
    cand.price_max = fresh.price_max
    cand.currency = fresh.currency
    # Propagate to the linked event via the SAME upsert as first ingest: it reads the raw's CURRENT
    # sessions, sets price from the candidate, stamps last_seen_at — so a new date appears, a stale one
    # stops being re-seen (falls to prune_stale_occurrences), and the price lands.
    link = (await db.execute(select(EventSource).where(EventSource.raw_id == raw_id))).scalars().first()
    if link is not None:
        event = await db.get(Event, link.event_id)
        venue = await db.get(Venue, cand.venue_id) if cand.venue_id else None
        if event is not None:
            await _upsert_occurrences(db, event, cand, venue, raw_id)
    raw.processed_hash = raw.content_hash
    return "refreshed"


async def dedup_and_upsert_event(
    db: AsyncSession,
    candidate: EventCandidate,
    source_id: int,
    raw_id: int,
    category: str,
    subcategory: str,
    tags: list[str],
    venue: Venue | None,
    llm=None,
) -> MatchDecision:
    existing_source_link = (await db.execute(select(EventSource).where(EventSource.raw_id == raw_id))).scalar_one_or_none()
    if existing_source_link:
        existing_event = await db.get(Event, existing_source_link.event_id)
        if existing_event is not None:
            # Re-ingest of a raw whose content changed: already mapped to an event, so skip re-dedup,
            # but DO refresh its occurrences — otherwise dates/prices are frozen after the first ingest.
            await _upsert_occurrences(db, existing_event, candidate, venue, raw_id)
        return MatchDecision(
            decision="auto-merge",
            score=1.0,
            matched_event_id=str(existing_event.event_id) if existing_event else "",
        )

    # An event lives at one physical PLACE, so a duplicate must share the
    # candidate's venue (the same Moscow day is enforced below). Anchoring on the
    # venue — not on title alone — is what keeps two different stagings of the same
    # play at two theatres ("Безымянная звезда" at four venues) from collapsing
    # into one event. Cross-source records that resolved to *different* venue rows
    # for one place are reunited by venue dedup first, then matched here. A
    # placeless candidate (no venue) can only fall back to an identical title key
    # among other placeless events. This also replaces an unordered ``LIMIT 400``
    # over the whole day window that randomly missed the existing event.
    cand_msk_day = candidate.date_start.astimezone(_MSK).date() if candidate.date_start else None
    cand_nkey = title_nkey(candidate.title)
    title_nkey_sql = func.regexp_replace(
        func.translate(func.lower(Event.canonical_title), "ё", "е"), "[^0-9a-zа-я]", "", "g"
    )
    stmt = select(Event, EventOccurrence).join(EventOccurrence, EventOccurrence.event_id == Event.event_id)
    if candidate.date_start:
        local = candidate.date_start.astimezone(_MSK)
        lo = local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        hi = local.replace(hour=23, minute=59, second=59, microsecond=0) + timedelta(days=1)
        stmt = stmt.where(and_(EventOccurrence.date_start >= lo, EventOccurrence.date_start <= hi))
    if venue is not None:
        stmt = stmt.where(EventOccurrence.venue_id == venue.venue_id)
    elif cand_nkey:
        stmt = stmt.where(and_(title_nkey_sql == cand_nkey, EventOccurrence.venue_id.is_(None)))
    else:  # no title and no venue — nothing to match on
        stmt = None
    matches = (await db.execute(stmt.order_by(EventOccurrence.date_start).limit(600))).all() if stmt is not None else []

    # Same place (guaranteed by the anchor) + same Moscow day + same event by title
    # (exact / transliterated / subset) → merge. Plus an exact-time collision: a
    # venue can't run two shows at the same instant, so the same venue + identical
    # start + a merely *fuzzy*-similar title (one source added a subtitle) is also
    # the same event. Nothing else auto-merges.
    strong: Event | None = None
    for event, occurrence in matches:
        same_day = bool(cand_msk_day and occurrence.date_start.astimezone(_MSK).date() == cand_msk_day)
        if not same_day:
            continue
        exact_time = candidate.date_start is not None and occurrence.date_start == candidate.date_start
        if same_event(event.canonical_title, candidate.title) or (
            exact_time and (
                same_slot_title(event.canonical_title, candidate.title)
                or same_event(event.canonical_title, candidate.title, level="fuzzy", strict_numbers=False)
            )
        ):
            strong = event
            break

    # The rules can't crack declension/initials/wrapper-word variants ("Концерт
    # Ансамбля … им. В.С. Локтева" vs "Ансамбль … им. Локтева"). When a new event
    # collides on the SAME venue + EXACT instant with one that shares a distinctive
    # word, ask the LLM right here at write time — no waiting on a cron. Cached, so a
    # repeat pair is free; the venue+time block keeps this to a handful of calls.
    cand_venue_id = venue.venue_id if venue else None
    if strong is None and llm is not None and candidate.date_start is not None and cand_venue_id is not None:
        cand_tok = {t for t in translit_tokens(candidate.title) if len(t) >= 4}
        for event, occurrence in matches:
            if occurrence.venue_id != cand_venue_id or occurrence.date_start != candidate.date_start:
                continue
            if not (cand_tok & {t for t in translit_tokens(event.canonical_title) if len(t) >= 4}):
                continue
            verdict = await llm.same_event(event.canonical_title, candidate.title)
            if verdict.get("same") and float(verdict.get("confidence", 0)) >= 0.7:
                strong = event
                break

    if strong is not None:
        decision = MatchDecision(decision="auto-merge", score=1.0, matched_event_id=str(strong.event_id))
        event = strong
    else:
        event = Event(
            canonical_title=candidate.title,
            canonical_description=candidate.description,
            category=category,
            subcategory=subcategory,
            age_limit=candidate.age_limit,
            primary_image_url=(candidate.images_json[0] if candidate.images_json else ""),
        )
        db.add(event)
        await db.commit()
        await db.refresh(event)
        decision = MatchDecision(decision="new-event", score=0.0, matched_event_id=str(event.event_id))

    # One occurrence per in-window session, idempotent on (event_id, date_start, venue_id).
    await _upsert_occurrences(db, event, candidate, venue, raw_id)

    db.add(
        EventSource(
            event_id=event.event_id,
            source_id=source_id,
            raw_id=raw_id,
            source_event_url=candidate.source_url,
        )
    )
    if tags and event.category == "other":
        event.category = category
        event.subcategory = subcategory
    db.add(event)
    await db.commit()

    return decision
