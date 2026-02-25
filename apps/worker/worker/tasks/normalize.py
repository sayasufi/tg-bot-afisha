from core.db.repositories.ingestion import get_raw, save_candidate, unprocessed_raw_ids
from core.db.session import SessionLocal
from pipeline.normalizer.rules import RuleBasedNormalizer

from apps.worker.worker.celery_app import celery_app


@celery_app.task(bind=True, max_retries=3)
def normalize_raw_events(self):
    db = SessionLocal()
    normalizer = RuleBasedNormalizer()
    try:
        raw_ids = unprocessed_raw_ids(db)
        created = 0
        for raw_id in raw_ids:
            raw = get_raw(db, raw_id)
            if not raw:
                continue
            candidates = normalizer.normalize(raw.raw_payload_json, raw.raw_text)
            for c in candidates:
                save_candidate(db, raw_id, c)
                created += 1
        return {"candidates": created}
    except Exception as exc:
        raise self.retry(exc=exc)
    finally:
        db.close()
