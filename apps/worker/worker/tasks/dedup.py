import asyncio

from sqlalchemy import select

from core.db.models import EventCandidate, RawEvent, Source
from core.db.repositories.ingestion import dedup_and_upsert_event
from core.db.session import SessionLocal
from pipeline.llm.service import LLMService

from apps.worker.worker.celery_app import celery_app


@celery_app.task(bind=True, max_retries=3)
def dedup_candidates(self):
    db = SessionLocal()
    llm = LLMService()
    try:
        stmt = (
            select(EventCandidate, RawEvent, Source)
            .join(RawEvent, RawEvent.raw_id == EventCandidate.raw_id)
            .join(Source, Source.source_id == RawEvent.source_id)
            .limit(200)
        )
        rows = db.execute(stmt).all()
        decisions = {"auto-merge": 0, "new-event": 0, "needs-review": 0}
        for candidate, raw, source in rows:
            category = "other"
            subcategory = ""
            tags: list[str] = []
            if not any(tag.startswith("category:") for tag in candidate.tags_json):
                classification = asyncio.run(llm.classify(candidate.title, candidate.description))
                category = classification.category
                subcategory = classification.subcategory
                tags = classification.tags
            else:
                for tag in candidate.tags_json:
                    if tag.startswith("category:"):
                        category = tag.split(":", 1)[1]
            decision = dedup_and_upsert_event(
                db,
                candidate=candidate,
                source_id=source.source_id,
                raw_id=raw.raw_id,
                category=category,
                subcategory=subcategory,
                tags=tags,
                venue=None,
            )
            decisions[decision.decision] += 1
        return decisions
    except Exception as exc:
        raise self.retry(exc=exc)
    finally:
        db.close()
