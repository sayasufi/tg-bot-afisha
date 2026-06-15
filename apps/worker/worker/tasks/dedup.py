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
