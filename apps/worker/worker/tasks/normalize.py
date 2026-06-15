import asyncio
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from core.config.settings import get_settings
from core.db.repositories.ingestion import get_raw, mark_raw_skipped, save_candidate, unprocessed_raw_ids
from core.db.session import WorkerAsyncSessionLocal
from core.tasklock import single_instance
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
    if now <= candidate.date_start <= until:
        return True
    # Ongoing events (exhibitions etc.): started in the past, still running.
    # The KudaGo connector admits these, so the normalizer must too.
    return bool(candidate.date_end and candidate.date_start <= now <= candidate.date_end)


@celery_app.task(bind=True, max_retries=3)
@single_instance("normalize")
def normalize_raw_events(self):
    try:
        return asyncio.run(_normalize_impl())
    except Exception as exc:
        raise self.retry(exc=exc)


async def _normalize_impl() -> dict:
    settings = get_settings()
    normalizer = RuleBasedNormalizer()
    llm_extractor = LLMExtractionService()
    async with WorkerAsyncSessionLocal() as db:
        raw_ids = await unprocessed_raw_ids(db)
        created = 0
        skipped = 0
        skipped_reasons: Counter[str] = Counter()
        for raw_id in raw_ids:
            raw = await get_raw(db, raw_id)
            if not raw:
                continue

            source_name = raw.source.name if raw.source else ""
            payload = raw.raw_payload_json
            if _is_telegram_source_name(source_name):
                extracted, skip_reason = await llm_extractor.extract_event_with_reason(
                    raw.raw_text, city_hint=settings.default_city
                )
                if extracted is None:
                    skipped += 1
                    skipped_reasons[skip_reason] += 1
                    await mark_raw_skipped(db, raw, skip_reason)
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
            saved_for_raw = 0
            last_skip_reason = ""
            for c in candidates:
                if source_name == "kudago" and not _is_kudago_candidate_in_window(c):
                    skipped += 1
                    last_skip_reason = "kudago_out_of_window"
                    skipped_reasons[last_skip_reason] += 1
                    continue
                if _is_telegram_source_name(source_name) and not _is_candidate_complete(c):
                    skipped += 1
                    last_skip_reason = _candidate_incomplete_reason(c)
                    skipped_reasons[last_skip_reason] += 1
                    logger.info(
                        "normalize_skip_candidate",
                        extra={"raw_id": raw_id, "source": source_name, "reason": last_skip_reason},
                    )
                    continue
                await save_candidate(db, raw_id, c)
                created += 1
                saved_for_raw += 1
            if not saved_for_raw and last_skip_reason:
                await mark_raw_skipped(db, raw, last_skip_reason)
        stats = {
            "candidates": created,
            "skipped": skipped,
            "skipped_reasons": dict(skipped_reasons),
        }
        logger.info("normalize_summary", extra=stats)
        return stats
