import asyncio

from sqlalchemy import select

from core.db.models import EventCandidate, EventSource, RawEvent, Source
from core.db.repositories.ingestion import dedup_and_upsert_event, get_venue
from core.db.session import WorkerAsyncSessionLocal
from pipeline.llm.service import LLMService


async def _dedup_impl() -> dict:
    llm = LLMService()
    async with WorkerAsyncSessionLocal() as db:
        # Only candidates that enrich has finished (venue_id set) and that are
        # not yet linked to an event; ordered so old rows cannot starve new ones.
        stmt = (
            select(EventCandidate, RawEvent, Source)
            .join(RawEvent, RawEvent.raw_id == EventCandidate.raw_id)
            .join(Source, Source.source_id == RawEvent.source_id)
            .outerjoin(EventSource, EventSource.raw_id == EventCandidate.raw_id)
            .where(EventSource.id.is_(None))
            .where(EventCandidate.venue_id.is_not(None))
            .order_by(EventCandidate.candidate_id.asc())
            .limit(200)
        )
        rows = (await db.execute(stmt)).all()
        decisions = {"auto-merge": 0, "new-event": 0, "needs-review": 0}
        for candidate, raw, source in rows:
            category = "other"
            subcategory = ""
            tags: list[str] = []
            if not any(tag.startswith("category:") for tag in candidate.tags_json):
                classification = await llm.classify(candidate.title, candidate.description, candidate.tags_json)
                category = classification.category
                subcategory = classification.subcategory
                tags = classification.tags
            else:
                for tag in candidate.tags_json:
                    if tag.startswith("category:"):
                        category = tag.split(":", 1)[1]
            venue = await get_venue(db, candidate.venue_id) if candidate.venue_id else None
            decision = await dedup_and_upsert_event(
                db,
                candidate=candidate,
                source_id=source.source_id,
                raw_id=raw.raw_id,
                category=category,
                subcategory=subcategory,
                tags=tags,
                venue=venue,
            )
            decisions[decision.decision] += 1
        return decisions


def _merge_venues_impl() -> dict:
    """Periodic self-heal: collapse near-duplicate venues that slipped past the
    write-time reuse in ``get_or_create_venue`` (e.g. borderline name variants
    that only become certain once both venues co-host the same event). Idempotent.
    """
    from pipeline.maintenance.venues import merge_fuzzy_venues

    return merge_fuzzy_venues(apply=True)


def _merge_events_impl() -> dict:
    """Periodic self-heal for duplicate *events*: collapse cross-source records
    that share a Moscow day + venue/title-key and are the same event by title
    (safe tier only — exact / transliterated / punctuation-normalised; the fuzzy
    subset tier is left to a reviewed one-off, never merged unattended). Idempotent.
    """
    from pipeline.maintenance.events import merge_duplicate_events

    return merge_duplicate_events(apply=True, fuzzy=False)


_LLM_DEDUP_CAP = 200  # pairs judged per run (cached, so this is mostly a first-run bound)
_LLM_DEDUP_CONCURRENCY = 4
_LLM_DEDUP_MIN_CONFIDENCE = 0.7


async def _dedup_llm_impl(apply: bool = True, cap: int = _LLM_DEDUP_CAP) -> dict:
    """LLM-assisted dedup for the residual the rules can't crack: two events at the
    SAME venue + EXACT same time whose titles differ only by declension, initials,
    a wrapper word, etc. ("Концерт Ансамбля … им. В.С. Локтева" vs "Ансамбль … им.
    Локтева"). Blocking (venue+time) + a distinctive-shared-word pre-filter keep the
    judged set tiny; verdicts are Redis-cached (incl. negatives) so it's near-free
    in steady state. Only high-confidence "same" verdicts are merged."""
    from pipeline.maintenance.events import _cluster_to_canon, _commit_event_merges, llm_candidate_pairs
    from core.db.session import SessionLocal

    db = SessionLocal()
    try:
        _title, rank, candidates = llm_candidate_pairs(db)
    finally:
        db.close()
    candidates = candidates[:cap]
    if not candidates:
        return {"candidates": 0, "judged": 0, "confirmed": 0, "clusters": 0, "dup_events": 0, "applied": apply}

    llm = LLMService()
    sem = asyncio.Semaphore(_LLM_DEDUP_CONCURRENCY)

    async def judge(a, b, ta, tb):
        async with sem:
            v = await llm.same_event(ta, tb)
        return (a, b) if (v.get("same") and float(v.get("confidence", 0)) >= _LLM_DEDUP_MIN_CONFIDENCE) else None

    verdicts = await asyncio.gather(*[judge(*c) for c in candidates])
    confirmed = [p for p in verdicts if p]

    db = SessionLocal()
    try:
        n_clusters, canon_pairs = _cluster_to_canon(confirmed, rank)
        res = _commit_event_merges(db, canon_pairs, apply)
    finally:
        db.close()
    res.update({"candidates": len(candidates), "judged": len(candidates), "confirmed": len(confirmed), "clusters": n_clusters})
    return res
