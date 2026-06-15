import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

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
from pipeline.dedup.scorer import MatchDecision, score_candidate
from pipeline.normalizer.extractors import NormalizedCandidate

_OCCURRENCE_LOOKAHEAD_DAYS = 30
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


def _payload_session_dates(payload: object, now: datetime, until: datetime) -> list[tuple[datetime, datetime | None]]:
    """All in-window sessions from a source payload's ``dates`` rows (unix start/end),
    so one source event with several showtimes becomes several occurrences. Returns
    [] for payloads without ``dates`` (LLM/ldjson sources keep the single primary)."""
    rows = payload.get("dates") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
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
    return out[:8]


def get_active_sources(db: Session) -> list[Source]:
    return db.execute(select(Source).where(Source.is_active.is_(True))).scalars().all()


def get_source_by_name(db: Session, name: str) -> Source | None:
    return db.execute(select(Source).where(Source.name == name)).scalar_one_or_none()


def get_active_telegram_channels(db: Session) -> list[TelegramChannel]:
    stmt = select(TelegramChannel).where(TelegramChannel.is_active.is_(True)).order_by(TelegramChannel.channel_id.asc())
    return db.execute(stmt).scalars().all()


def ensure_source(db: Session, name: str, kind: str, base_url: str, config_json: dict | None = None) -> Source:
    source = get_source_by_name(db, name)
    if source:
        return source
    source = Source(name=name, kind=kind, base_url=base_url, config_json=config_json or {})
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def create_source_run(db: Session, source_id: int) -> SourceRun:
    run = SourceRun(source_id=source_id, status="running", started_at=datetime.now(timezone.utc))
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def finish_source_run(db: Session, run: SourceRun, status: str, stats: dict, error_text: str = "") -> None:
    run.status = status
    run.finished_at = datetime.now(timezone.utc)
    run.stats_json = stats
    run.error_text = error_text
    db.add(run)
    db.commit()


def upsert_raw_event(db: Session, source_id: int, external_id: str, payload: dict, raw_text: str) -> RawEvent:
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
    row = db.execute(stmt, execution_options={"populate_existing": True}).scalar_one()
    db.commit()
    return row


def bulk_upsert_raw_events(db: Session, source_id: int, records: list) -> int:
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
    db.execute(stmt)
    db.commit()
    return len(rows)


def save_candidate(db: Session, raw_id: int, candidate: NormalizedCandidate) -> EventCandidate:
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
    db.commit()
    db.refresh(row)
    return row


def unprocessed_raw_ids(db: Session, limit: int = 100) -> list[int]:
    stmt = (
        select(RawEvent.raw_id)
        .outerjoin(EventCandidate, EventCandidate.raw_id == RawEvent.raw_id)
        .where(EventCandidate.candidate_id.is_(None))
        .where(RawEvent.skip_reason == "")
        .order_by(RawEvent.raw_id.asc())
        .limit(limit)
    )
    return db.execute(stmt).scalars().all()


def mark_raw_skipped(db: Session, raw: RawEvent, reason: str) -> None:
    raw.skip_reason = (reason or "skipped")[:64]
    db.add(raw)
    db.commit()


def unresolved_candidate_ids(db: Session, limit: int = 100) -> list[int]:
    stmt = (
        select(EventCandidate.candidate_id)
        .outerjoin(EventSource, EventSource.raw_id == EventCandidate.raw_id)
        .where(EventSource.id.is_(None))
        .where(EventCandidate.venue_id.is_(None))
        .order_by(EventCandidate.candidate_id.asc())
        .limit(limit)
    )
    return db.execute(stmt).scalars().all()


def get_candidate(db: Session, candidate_id: int) -> EventCandidate | None:
    return db.get(EventCandidate, candidate_id)


def get_raw(db: Session, raw_id: int) -> RawEvent | None:
    return db.get(RawEvent, raw_id)


def get_or_create_venue(db: Session, name: str, address: str, city: str, country: str, lat: float | None, lon: float | None, provider: str, confidence: float) -> Venue:
    venue = db.execute(select(Venue).where(and_(Venue.name == name, Venue.address == address))).scalar_one_or_none()
    if venue:
        return venue
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
    venue_id = db.execute(stmt).scalar_one_or_none()
    db.commit()
    if venue_id is None:  # another worker inserted it first
        return db.execute(select(Venue).where(and_(Venue.name == name, Venue.address == address))).scalar_one()
    return db.get(Venue, venue_id)


def find_cached_venue(db: Session, name: str, city: str, country: str) -> Venue | None:
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
    return db.execute(stmt).scalar_one_or_none()


def unresolved_venue_ids(db: Session, limit: int = 200) -> list[int]:
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
    return db.execute(stmt).scalars().all()


def get_venue(db: Session, venue_id: int) -> Venue | None:
    return db.get(Venue, venue_id)


def dedup_and_upsert_event(
    db: Session,
    candidate: EventCandidate,
    source_id: int,
    raw_id: int,
    category: str,
    subcategory: str,
    tags: list[str],
    venue: Venue | None,
) -> MatchDecision:
    existing_source_link = db.execute(select(EventSource).where(EventSource.raw_id == raw_id)).scalar_one_or_none()
    if existing_source_link:
        existing_event = db.get(Event, existing_source_link.event_id)
        return MatchDecision(
            decision="auto-merge",
            score=1.0,
            matched_event_id=str(existing_event.event_id) if existing_event else "",
        )

    stmt = select(Event, EventOccurrence).join(EventOccurrence, EventOccurrence.event_id == Event.event_id)
    cand_msk_day = candidate.date_start.astimezone(_MSK).date() if candidate.date_start else None
    if candidate.date_start:
        # Match within the candidate's Moscow calendar day. The window is widened by a
        # day on each side (UTC bounds) and the exact MSK-day equality is enforced below,
        # so MSK-midnight events (stored on the previous UTC day) aren't missed.
        local = candidate.date_start.astimezone(_MSK)
        lo = local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        hi = local.replace(hour=23, minute=59, second=59, microsecond=0) + timedelta(days=1)
        stmt = stmt.where(and_(EventOccurrence.date_start >= lo, EventOccurrence.date_start <= hi))
    matches = db.execute(stmt.limit(400)).all()

    best: tuple[Event, float] | None = None
    for event, occurrence in matches:
        same_day = bool(cand_msk_day and occurrence.date_start.astimezone(_MSK).date() == cand_msk_day)
        score = score_candidate(
            event.canonical_title,
            candidate.title,
            same_day=same_day,
            geo_close=bool(venue and occurrence.venue_id == venue.venue_id),
        )
        if not best or score > best[1]:
            best = (event, score)

    if best and best[1] >= 0.87:
        event = best[0]
        decision = MatchDecision(decision="auto-merge", score=best[1], matched_event_id=str(event.event_id))
    elif best and best[1] >= 0.72:
        event = best[0]
        decision = MatchDecision(decision="needs-review", score=best[1], matched_event_id=str(event.event_id))
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
        db.commit()
        db.refresh(event)
        decision = MatchDecision(decision="new-event", score=0.0, matched_event_id=str(event.event_id))

    # One occurrence per in-window session: an event with several showtimes (e.g.
    # 16 & 23 June, 21:00) becomes several occurrences. Sources without a `dates`
    # list keep the single primary date. Upsert on (event_id, date_start, venue_id)
    # so re-ingesting updates instead of duplicating.
    raw = get_raw(db, raw_id)
    now = datetime.now(timezone.utc)
    until = now + timedelta(days=_OCCURRENCE_LOOKAHEAD_DAYS)
    sessions = _payload_session_dates(raw.raw_payload_json if raw else None, now, until)
    if not sessions:
        sessions = [(candidate.date_start or datetime.now(timezone.utc), candidate.date_end)]
    occ_venue_id = venue.venue_id if venue else None
    venue_filter = EventOccurrence.venue_id.is_(None) if occ_venue_id is None else EventOccurrence.venue_id == occ_venue_id
    for occ_start, occ_end in sessions:
        occurrence = db.execute(
            select(EventOccurrence).where(
                and_(
                    EventOccurrence.event_id == event.event_id,
                    EventOccurrence.date_start == occ_start,
                    venue_filter,
                )
            )
        ).scalars().first()
        if occurrence:
            occurrence.date_end = occ_end
            occurrence.price_min = candidate.price_min
            occurrence.price_max = candidate.price_max
            occurrence.currency = candidate.currency
            occurrence.source_best_url = candidate.source_url
        else:
            db.add(
                EventOccurrence(
                    event_id=event.event_id,
                    venue_id=occ_venue_id,
                    date_start=occ_start,
                    date_end=occ_end,
                    price_min=candidate.price_min,
                    price_max=candidate.price_max,
                    currency=candidate.currency,
                    source_best_url=candidate.source_url,
                )
            )
    db.flush()

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
    db.commit()

    return decision
