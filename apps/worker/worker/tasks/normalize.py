import asyncio
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from core.config.settings import get_settings
from core.db.repositories.ingestion import (
    get_raw,
    mark_raw_skipped,
    reprocess_raw,
    save_candidate,
    stale_structured_raw_ids,
    unprocessed_raw_ids,
)
from core.db.session import WorkerAsyncSessionLocal
from pipeline.llm.extraction_service import LLMExtractionService
from pipeline.normalizer.rules import RuleBasedNormalizer


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
    # Must match the KudaGo connector's _LOOKAHEAD_DAYS (365) and the occurrence
    # window — a 30-day gate here silently dropped events the connector fetched
    # 31..365 days out (a play's autumn run never reached the map).
    until = now + timedelta(days=365)
    if now <= candidate.date_start <= until:
        return True
    # Ongoing events (exhibitions etc.): started in the past, still running.
    # The KudaGo connector admits these, so the normalizer must too.
    return bool(candidate.date_end and candidate.date_start <= now <= candidate.date_end)


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
            if saved_for_raw:
                raw.processed_hash = raw.content_hash  # mark the content version this candidate was built from
                await db.commit()
            elif last_skip_reason:
                await mark_raw_skipped(db, raw, last_skip_reason)
        stats = {
            "candidates": created,
            "skipped": skipped,
            "skipped_reasons": dict(skipped_reasons),
        }
        logger.info("normalize_summary", extra=stats)
        return stats


async def _reprocess_changed_impl(max_batches: int = 12) -> dict:
    """Re-normalize structured-source raws whose content changed since their candidate was built, so
    updated dates/prices propagate instead of freezing at first-ingest. Bounded per run (the schedule
    drains the rest); per-raw commit isolates a bad raw, and processed_hash is always stamped so the
    selector advances and never loops."""
    normalizer = RuleBasedNormalizer()
    refreshed = errors = 0
    async with WorkerAsyncSessionLocal() as db:
        for _ in range(max_batches):
            ids = await stale_structured_raw_ids(db, limit=200)
            if not ids:
                break
            for rid in ids:
                try:
                    res = await reprocess_raw(db, rid, normalizer)
                    await db.commit()
                    if res == "refreshed":
                        refreshed += 1
                except Exception:
                    await db.rollback()
                    errors += 1
                    logger.warning("reprocess_failed", extra={"raw_id": rid}, exc_info=True)
                    try:  # stamp so a permanently-failing raw doesn't loop the selector forever
                        raw = await get_raw(db, rid)
                        if raw is not None:
                            raw.processed_hash = raw.content_hash
                            await db.commit()
                    except Exception:
                        await db.rollback()
    stats = {"refreshed": refreshed, "errors": errors}
    logger.info("reprocess_summary", extra=stats)
    return stats
