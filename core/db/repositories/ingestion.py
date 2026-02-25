import hashlib
from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from core.db.models import (
    Event,
    EventCandidate,
    EventOccurrence,
    EventSource,
    IngestInbox,
    RawEvent,
    Source,
    SourceRun,
    Venue,
)
from pipeline.dedup.scorer import MatchDecision, score_candidate
from pipeline.normalizer.extractors import NormalizedCandidate


def get_active_sources(db: Session) -> list[Source]:
    return db.execute(select(Source).where(Source.is_active.is_(True))).scalars().all()


def get_source_by_name(db: Session, name: str) -> Source | None:
    return db.execute(select(Source).where(Source.name == name)).scalar_one_or_none()


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
    run = SourceRun(source_id=source_id, status="running", started_at=datetime.utcnow())
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def finish_source_run(db: Session, run: SourceRun, status: str, stats: dict, error_text: str = "") -> None:
    run.status = status
    run.finished_at = datetime.utcnow()
    run.stats_json = stats
    run.error_text = error_text
    db.add(run)
    db.commit()


def upsert_raw_event(db: Session, source_id: int, external_id: str, payload: dict, raw_text: str) -> RawEvent:
    existing = db.execute(
        select(RawEvent).where(and_(RawEvent.source_id == source_id, RawEvent.external_id == external_id))
    ).scalar_one_or_none()
    content_hash = hashlib.sha256(raw_text.encode("utf-8", errors="ignore")).hexdigest()
    if existing:
        existing.raw_payload_json = payload
        existing.raw_text = raw_text
        existing.content_hash = content_hash
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing

    row = RawEvent(
        source_id=source_id,
        external_id=external_id,
        raw_payload_json=payload,
        raw_text=raw_text,
        content_hash=content_hash,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


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
        .limit(limit)
    )
    return db.execute(stmt).scalars().all()


def unresolved_candidate_ids(db: Session, limit: int = 100) -> list[int]:
    stmt = (
        select(EventCandidate.candidate_id)
        .outerjoin(EventSource, EventSource.raw_id == EventCandidate.raw_id)
        .where(EventSource.id.is_(None))
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
    venue = Venue(
        name=name,
        address=address,
        city=city,
        country=country,
        geocode_provider=provider,
        geocode_confidence=confidence,
    )
    if lat is not None and lon is not None:
        venue.geom = func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)
    db.add(venue)
    db.commit()
    db.refresh(venue)
    return venue


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
    stmt = select(Event, EventOccurrence).join(EventOccurrence, EventOccurrence.event_id == Event.event_id)
    if candidate.date_start:
        stmt = stmt.where(
            and_(
                EventOccurrence.date_start >= candidate.date_start.replace(hour=0, minute=0, second=0),
                EventOccurrence.date_start <= candidate.date_start.replace(hour=23, minute=59, second=59),
            )
        )
    matches = db.execute(stmt.limit(200)).all()

    best: tuple[Event, float] | None = None
    for event, occurrence in matches:
        score = score_candidate(
            event.canonical_title,
            candidate.title,
            same_day=(candidate.date_start.date() == occurrence.date_start.date()) if candidate.date_start else False,
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

    occurrence = EventOccurrence(
        event_id=event.event_id,
        venue_id=venue.venue_id if venue else None,
        date_start=candidate.date_start or datetime.utcnow(),
        date_end=candidate.date_end,
        price_min=candidate.price_min,
        price_max=candidate.price_max,
        currency=candidate.currency,
        source_best_url=candidate.source_url,
    )
    db.add(occurrence)
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


def get_unprocessed_inbox_rows(db: Session, limit: int = 100) -> list[IngestInbox]:
    return db.execute(select(IngestInbox).where(IngestInbox.processed.is_(False)).limit(limit)).scalars().all()


def mark_inbox_processed(db: Session, inbox_id: int) -> None:
    row = db.get(IngestInbox, inbox_id)
    if not row:
        return
    row.processed = True
    db.add(row)
    db.commit()
