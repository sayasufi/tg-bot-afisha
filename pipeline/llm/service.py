import asyncio
import hashlib
import json
import logging

import redis

from core.config.settings import get_settings
from pipeline.llm.adapters.base import CategoryResult
from pipeline.llm.adapters.http_chat_adapter import HTTPChatAdapter

logger = logging.getLogger(__name__)

# Classification is deterministic given (title, description, hints) + prompt, so we
# cache results in Redis and skip the ~20s LLM round-trip for repeat/re-ingested
# events. Bump the version tag whenever the classify prompt changes.
_CACHE_PREFIX = "llm:classify:v4:"
_CACHE_TTL_SECONDS = 14 * 24 * 3600
# Same-event dedup judgments. Cached BOTH ways (incl. "different") so a non-matching
# same-slot pair isn't re-asked every self-heal run. Bump v when the prompt changes.
_SAME_EVENT_PREFIX = "llm:samevent:v1:"
_SAME_EVENT_TTL_SECONDS = 30 * 24 * 3600

# A plain (sync) Redis client: not bound to an event loop, so it survives the
# per-candidate asyncio.run() calls in the worker, and a local round-trip (~ms) is
# negligible next to the LLM latency it saves.
_redis_client: redis.Redis | None = None


def _get_redis(url: str) -> redis.Redis | None:
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = redis.from_url(url, socket_timeout=2, socket_connect_timeout=2, decode_responses=True)
        except Exception:  # pragma: no cover - cache is best-effort
            logger.warning("llm_cache_init_failed", exc_info=True)
            return None
    return _redis_client


class LLMService:
    def __init__(self) -> None:
        settings = get_settings()
        self.adapter = HTTPChatAdapter(
            base_url=settings.llm_api_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
        )
        self._redis_url = settings.redis_url

    @staticmethod
    def _cache_key(title: str, description: str, hints: list[str] | None) -> str:
        raw = "\x1f".join([title or "", (description or "")[:600], ",".join(sorted(hints or []))])
        return _CACHE_PREFIX + hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()

    async def classify(self, title: str, description: str, hints: list[str] | None = None) -> CategoryResult:
        key = self._cache_key(title, description, hints)
        cache = _get_redis(self._redis_url)
        if cache is not None:
            try:
                hit = await asyncio.to_thread(cache.get, key)
                if hit:
                    return CategoryResult(**json.loads(hit))
            except Exception:  # cache read must never break classification
                logger.debug("llm_cache_read_failed", exc_info=True)

        try:
            result = await self.adapter.classify(title, description, hints)
        except Exception:
            logger.warning("llm_classify_failed", extra={"title": (title or "")[:80]}, exc_info=True)
            return CategoryResult(category="other", subcategory="", tags=[], confidence=0.0, provider="fallback")

        # Only cache real classifications, not the empty/uncertain fallback.
        if cache is not None and (result.category != "other" or result.tags):
            try:
                await asyncio.to_thread(
                    cache.set,
                    key,
                    json.dumps(
                        {
                            "category": result.category,
                            "subcategory": result.subcategory,
                            "tags": result.tags,
                            "confidence": result.confidence,
                            "provider": result.provider,
                        }
                    ),
                    ex=_CACHE_TTL_SECONDS,
                )
            except Exception:
                logger.debug("llm_cache_write_failed", exc_info=True)
        return result

    async def same_event(self, title_a: str, title_b: str) -> dict:
        """Judge whether two same-venue+same-time titles are one event. Returns
        {"same": bool, "confidence": float}. Order-independent + Redis-cached. Any
        transport/parse failure is a safe no-match (never merge on a bad call)."""
        a, b = (title_a or "").strip(), (title_b or "").strip()
        lo, hi = sorted((a, b))
        key = _SAME_EVENT_PREFIX + hashlib.sha256(f"{lo}\x1f{hi}".encode("utf-8", "ignore")).hexdigest()
        cache = _get_redis(self._redis_url)
        if cache is not None:
            try:
                hit = await asyncio.to_thread(cache.get, key)
                if hit:
                    return json.loads(hit)
            except Exception:
                logger.debug("llm_dedup_cache_read_failed", exc_info=True)
        try:
            same, conf = await self.adapter.judge_same_event(a, b)
            verdict = {"same": bool(same), "confidence": float(conf)}
        except Exception:
            logger.warning("llm_same_event_failed", extra={"a": a[:60], "b": b[:60]}, exc_info=True)
            return {"same": False, "confidence": 0.0}
        if cache is not None:
            try:
                await asyncio.to_thread(cache.set, key, json.dumps(verdict), ex=_SAME_EVENT_TTL_SECONDS)
            except Exception:
                logger.debug("llm_dedup_cache_write_failed", exc_info=True)
        return verdict
