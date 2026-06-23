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
    upsert_raw_event,
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


def _aware(dt: datetime | None) -> datetime | None:
    """Treat a naive datetime as UTC — the LLM returns ISO without an offset, so candidate dates can be
    naive while now() is aware (a direct comparison raises TypeError)."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _is_telegram_candidate_in_window(candidate) -> bool:
    """Keep only upcoming (or still-ongoing) telegram events. A «сегодня»-post, resolved to the post's
    date, is already PAST by the time we extract it (fetch lag) — drop it rather than surface a passed
    event with a today-looking date."""
    ds = _aware(candidate.date_start)
    if ds is None:
        return False
    now = datetime.now(timezone.utc)
    if ds >= now - timedelta(hours=6):  # upcoming, or a tonight-event still within reach
        return True
    de = _aware(candidate.date_end)
    return bool(de and de >= now)  # ongoing run


def _telegram_payload(extracted, base_payload: dict, v_name: str, v_addr: str) -> dict:
    """Fold one extracted event into the structured payload the rule normalizer consumes — keeps the
    post's images/published_at and fills venue/address from the channel binding when absent."""
    base = base_payload or {}
    return {
        **base,
        "title": extracted.title,
        "description": extracted.description,
        "startDate": extracted.date_start,
        "endDate": extracted.date_end or None,
        "venue": extracted.venue or v_name,           # fall back to the channel's bound venue
        "address": extracted.address or v_addr,       # …and its address (NULL → LLM's own)
        "address_candidates": extracted.address_candidates,
        "price": extracted.price_text,
        "age_restriction": extracted.age_limit,
        "tags": list(dict.fromkeys([*(base.get("tags", []) if isinstance(base, dict) else []), *extracted.tags])),
    }


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
                base_payload = raw.raw_payload_json or {}
                if base_payload.get("_split_child"):
                    # A child of a multi-event post — already structured by the parent pass, no LLM needed.
                    payload = base_payload
                else:
                    # Optional venue binding for venue-specific channels (NULL for general channels): a hint
                    # to the LLM + a fill for venue/address when the post doesn't name the place.
                    _cfg = (raw.source.config_json if raw.source else None) or {}
                    v_name = _cfg.get("venue_name") or ""
                    v_addr = _cfg.get("venue_address") or ""
                    venue_hint = ", ".join(p for p in (v_name, v_addr) if p)
                    # The post's publish date anchors relative dates («сегодня»/«завтра») — otherwise the LLM
                    # resolves «сегодня» to the EXTRACTION day, not the post day.
                    post_date = str(base_payload.get("published_at") or "")[:10]
                    events, skip_reason = await llm_extractor.extract_events_with_reason(
                        raw.raw_text, city_hint=settings.default_city, venue_hint=venue_hint, post_date=post_date
                    )
                    if not events:
                        skipped += 1
                        skipped_reasons[skip_reason] += 1
                        await mark_raw_skipped(db, raw, skip_reason)
                        logger.info(
                            "normalize_skip_telegram",
                            extra={"raw_id": raw_id, "source": source_name, "reason": skip_reason},
                        )
                        continue
                    if len(events) > 1:
                        # A schedule post holds many events on different dates. Fan out into one CHILD raw
                        # per event (external_id "<parent>#<idx>") so each becomes its own event — this
                        # keeps the one-raw→one-event dedup invariant. The parent raw is just a container:
                        # mark it processed with no candidate of its own. Children process next cycle.
                        for idx, ev in enumerate(events):
                            child_payload = {**_telegram_payload(ev, base_payload, v_name, v_addr), "_split_child": True}
                            await upsert_raw_event(db, raw.source_id, f"{raw.external_id}#{idx}", child_payload, raw.raw_text)
                        raw.processed_hash = raw.content_hash
                        await db.commit()
                        skipped_reasons["telegram_split"] += 1
                        continue
                    payload = _telegram_payload(events[0], base_payload, v_name, v_addr)

            candidates = normalizer.normalize(payload, raw.raw_text)
            saved_for_raw = 0
            last_skip_reason = ""
            for c in candidates:
                if source_name == "kudago" and not _is_kudago_candidate_in_window(c):
                    skipped += 1
                    last_skip_reason = "kudago_out_of_window"
                    skipped_reasons[last_skip_reason] += 1
                    continue
                if _is_telegram_source_name(source_name) and not _is_telegram_candidate_in_window(c):
                    skipped += 1
                    last_skip_reason = "telegram_past_event"
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
