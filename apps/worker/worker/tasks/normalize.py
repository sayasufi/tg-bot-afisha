import asyncio
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from core.db.repositories.ingestion import get_raw, save_candidate, unprocessed_raw_ids
from core.db.session import SessionLocal
from pipeline.llm.extraction_service import LLMExtractionService
from pipeline.normalizer.rules import RuleBasedNormalizer

from apps.worker.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


def _is_telegram_source_name(name: str) -> bool:
    return name.startswith("telegram")


def _is_candidate_complete(candidate) -> bool:
    if not candidate.title or not candidate.title.strip():
        return False
    if candidate.date_start is None:
        return False
    if not ((candidate.address or "").strip() or (candidate.venue or "").strip()):
        return False
    return True


def _candidate_incomplete_reason(candidate) -> str:
    if not candidate.title or not candidate.title.strip():
        return "candidate_missing_title"
    if candidate.date_start is None:
        return "candidate_missing_date"
    if not ((candidate.address or "").strip() or (candidate.venue or "").strip()):
        return "candidate_missing_venue_address"
    return "candidate_incomplete"


def _is_kudago_candidate_in_window(candidate) -> bool:
    if candidate.date_start is None:
        return False
    now = datetime.now(timezone.utc)
    until = now + timedelta(days=30)
    return now <= candidate.date_start <= until


@celery_app.task(bind=True, max_retries=3)
def normalize_raw_events(self):
    db = SessionLocal()
    normalizer = RuleBasedNormalizer()
    llm_extractor = LLMExtractionService()
    try:
        raw_ids = unprocessed_raw_ids(db)
        created = 0
        skipped = 0
        skipped_reasons: Counter[str] = Counter()
        for raw_id in raw_ids:
            raw = get_raw(db, raw_id)
            if not raw:
                continue

            source_name = raw.source.name if raw.source else ""
            payload = raw.raw_payload_json
            if _is_telegram_source_name(source_name):
                extracted, skip_reason = asyncio.run(llm_extractor.extract_event_with_reason(raw.raw_text, city_hint="Moscow"))
                if extracted is None:
                    skipped += 1
                    skipped_reasons[skip_reason] += 1
                    logger.info(
                        "normalize_skip_telegram",
                        extra={"raw_id": raw_id, "source": source_name, "reason": skip_reason},
                    )
                    continue
                payload = {
                    **(raw.raw_payload_json or {}),
                    "title": extracted.title,
                    "description": extracted.description,
                    "startDate": extracted.date_start,
                    "endDate": extracted.date_end or None,
                    "venue": extracted.venue,
                    "address": extracted.address,
                    "address_candidates": extracted.address_candidates,
                    "price": extracted.price_text,
                    "age_restriction": extracted.age_limit,
                    "tags": list(
                        dict.fromkeys(
                            [*(raw.raw_payload_json.get("tags", []) if isinstance(raw.raw_payload_json, dict) else []), *extracted.tags]
                        )
                    ),
                }

            candidates = normalizer.normalize(payload, raw.raw_text)
            for c in candidates:
                if source_name == "kudago" and not _is_kudago_candidate_in_window(c):
                    skipped += 1
                    skipped_reasons["kudago_out_of_window"] += 1
                    continue
                if _is_telegram_source_name(source_name) and not _is_candidate_complete(c):
                    skipped += 1
                    reason = _candidate_incomplete_reason(c)
                    skipped_reasons[reason] += 1
                    logger.info(
                        "normalize_skip_candidate",
                        extra={"raw_id": raw_id, "source": source_name, "reason": reason},
                    )
                    continue
                save_candidate(db, raw_id, c)
                created += 1
        stats = {
            "candidates": created,
            "skipped": skipped,
            "skipped_reasons": dict(skipped_reasons),
        }
        logger.info("normalize_summary", extra=stats)
        return stats
    except Exception as exc:
        raise self.retry(exc=exc)
    finally:
        db.close()
