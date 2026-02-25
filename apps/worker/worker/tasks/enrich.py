import asyncio

from core.config.settings import get_settings
from core.db.repositories.ingestion import get_candidate, get_or_create_venue, unresolved_candidate_ids
from core.db.session import SessionLocal
from pipeline.geocoding.service import GeocodingService
from pipeline.llm.service import LLMService

from apps.worker.worker.celery_app import celery_app


@celery_app.task(bind=True, max_retries=3)
def enrich_candidates(self):
    db = SessionLocal()
    geocoder = GeocodingService()
    llm = LLMService()
    try:
        ids = unresolved_candidate_ids(db)
        enriched = 0
        for candidate_id in ids:
            candidate = get_candidate(db, candidate_id)
            if not candidate:
                continue

            geo = asyncio.run(geocoder.geocode(candidate.address, city_hint=None)) if candidate.address else None
            venue = get_or_create_venue(
                db,
                name=candidate.venue or "Unknown venue",
                address=candidate.address or "",
                city="",
                country=get_settings().default_country,
                lat=geo.lat if geo else None,
                lon=geo.lon if geo else None,
                provider=geo.provider if geo else "",
                confidence=geo.confidence if geo else 0.0,
            )
            classify = asyncio.run(llm.classify(candidate.title, candidate.description))
            candidate.tags_json = list(set(candidate.tags_json + classify.tags))
            if classify.category and classify.category != "other":
                candidate.tags_json.append(f"category:{classify.category}")
            db.add(candidate)
            db.add(venue)
            db.commit()
            enriched += 1
        return {"enriched": enriched}
    except Exception as exc:
        raise self.retry(exc=exc)
    finally:
        db.close()
