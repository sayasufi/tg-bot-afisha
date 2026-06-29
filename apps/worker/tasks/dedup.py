import asyncio
import logging

from sqlalchemy import select

from core.config.settings import get_settings
from core.db.models import EventCandidate, EventSource, RawEvent, Source
from core.db.repositories.ingestion import dedup_and_upsert_event, get_venue
from core.db.session import WorkerAsyncSessionLocal
from pipeline.llm.service import LLMService

_log = logging.getLogger(__name__)

# Batch fan-out for in-flight LLM classify calls. The REAL service-wide cap is the shared limiter in
# core.services.llm_limiter (settings.llm_max_concurrency); this just sizes the gather so it can fill that
# budget without spawning idle pollers beyond it.
_CLASSIFY_CONCURRENCY = get_settings().llm_max_concurrency


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

        # Pre-classify CONCURRENTLY (bounded). The LLM classify is a ~20s-timeout-prone
        # network call with a ~43% cache miss rate; running it serially per candidate
        # made dedup — the LAST stage before an event becomes visible — a multi-minute
        # tail. The upsert loop below stays SERIAL (its dedup lookups/writes depend on
        # prior commits, e.g. two candidates that are duplicates of each other).
        need = [c for c, _r, _s in rows if not any(t.startswith("category:") for t in c.tags_json)]
        sem = asyncio.Semaphore(_CLASSIFY_CONCURRENCY)

        async def _classify(candidate):
            async with sem:
                return await llm.classify(candidate.title, candidate.description, candidate.tags_json)

        classified = dict(zip(
            (c.candidate_id for c in need),
            await asyncio.gather(*[_classify(c) for c in need]),
        )) if need else {}

        decisions = {"auto-merge": 0, "new-event": 0, "needs-review": 0}
        for candidate, raw, source in rows:
            # Isolate each candidate: one that deterministically raises (e.g. a bad
            # write-time judge call, a constraint blow-up) must not become a permanent
            # head-of-line block for every candidate ordered after it. Log with the id,
            # roll back the failed transaction so the session is usable, and continue.
            try:
                category = "other"
                subcategory = ""
                tags: list[str] = []
                classification = classified.get(candidate.candidate_id)
                if classification is not None:
                    category = classification.category
                    subcategory = classification.subcategory
                    tags = classification.tags
                else:
                    for tag in candidate.tags_json:
                        if tag.startswith("category:"):
                            category = tag.split(":", 1)[1]
                # Owner: NO lectures from Timepad. The connector drops the obvious ones, but the
                # "Искусство и культура" → LLM path can still classify a stray as a lecture — delete it
                # here (deterministic source+category gate) so it never becomes an event or re-loops.
                if source.name == "timepad" and category == "lecture":
                    await db.delete(candidate)
                    await db.commit()
                    continue
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
                    llm=llm,  # write-time LLM judge for same-venue+time look-alikes
                )
                decisions[decision.decision] += 1
            except Exception:
                _log.exception("dedup: candidate %s failed, skipping", candidate.candidate_id)
                await db.rollback()
                continue
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
_LLM_DEDUP_CONCURRENCY = get_settings().llm_max_concurrency  # capped service-wide by core.services.llm_limiter
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


_FUZZY_LLM_CAP = 300
_FUZZY_LLM_MIN_CONFIDENCE = 0.95  # higher bar than the exact-time pass — venue+DAY is a weaker anchor


async def _dedup_fuzzy_llm_impl(apply: bool = True, cap: int = _FUZZY_LLM_CAP) -> dict:
    """LLM pass over the REVIEW-tier fuzzy pairs (subset-with-distinctive-word / high-ratio at the same
    venue+Moscow day) that the rules deliberately never auto-merge — e.g. "Сергей Трофимов" vs
    "Юбилейный концерт Сергея Трофимова", "Лекция «X»" vs "X". Judge each with the cached LLM
    same_event and merge only high-confidence twins. Skip any pair whose titles differ by a non-year
    number (age ranges «(6-10)» vs «(11-15)», parts) so distinct sessions never collapse. Verdicts are
    Redis-cached (incl. negatives), so steady-state runs are near-free."""
    from pipeline.maintenance.events import find_pairs, _cluster_to_canon, _commit_event_merges
    from core.matching.title_match import _numbers
    from core.db.session import SessionLocal

    db = SessionLocal()
    try:
        title, rank, _safe, fuzzy = find_pairs(db)
    finally:
        db.close()
    fuzzy = fuzzy[:cap]
    if not fuzzy:
        return {"fuzzy": 0, "confirmed": 0, "dup_events": 0, "applied": apply}

    llm = LLMService()
    sem = asyncio.Semaphore(_LLM_DEDUP_CONCURRENCY)

    async def judge(a, b):
        ta, tb = title.get(a, ""), title.get(b, "")
        if _numbers(ta) != _numbers(tb):  # different age/part numbers → distinct sessions, never merge
            return None
        async with sem:
            v = await llm.same_event(ta, tb)
        return (a, b) if (v.get("same") and float(v.get("confidence", 0)) >= _FUZZY_LLM_MIN_CONFIDENCE) else None

    confirmed = [p for p in await asyncio.gather(*[judge(a, b) for a, b in fuzzy]) if p]

    db = SessionLocal()
    try:
        n_clusters, canon_pairs = _cluster_to_canon(confirmed, rank)
        res = _commit_event_merges(db, canon_pairs, apply)
    finally:
        db.close()
    res.update({"fuzzy": len(fuzzy), "confirmed": len(confirmed), "clusters": n_clusters})
    return res
