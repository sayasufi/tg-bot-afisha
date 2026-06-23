"""Service-wide LLM concurrency limiter — one shared budget of in-flight LLM requests.

Every LLM provider call (category classify, dedup same-event judge, Telegram-post extraction) acquires
a slot here first, so the number of concurrent in-flight LLM requests across the WHOLE service is capped
at `settings.llm_max_concurrency` (default 20). A plain asyncio.Semaphore only bounds ONE process; the
service runs the API (several uvicorn workers) and the Prefect worker as separate processes, so the
budget lives in Redis as a distributed semaphore.

Each slot carries a lease (a TTL on its sorted-set score): a crashed holder's slot is auto-reclaimed,
so the budget can never leak permanently. If Redis is unavailable the limiter degrades to a
process-local semaphore — concurrency is then bounded per-process, but LLM work is never blocked by a
Redis outage. If a slot can't be acquired within a generous deadline it proceeds anyway, so a stuck
budget never deadlocks the ingestion pipeline.
"""
import asyncio
import contextlib
import time
import uuid

from core.config.settings import get_settings
from core.redis import get_redis

_KEY = "llm:slots"
_LEASE_TTL = 90.0        # seconds — comfortably above the LLM request timeout (~20s) a slow call holds
_ACQUIRE_TIMEOUT = 90.0  # give up waiting for a slot after this and proceed (never stall a batch)
_POLL = 0.05             # seconds between acquire attempts while the budget is full

# Atomic acquire: reclaim slots whose lease expired, then claim one IFF under the limit.
# KEYS[1] = slots set; ARGV = now, lease_ttl, limit, member.
_ACQUIRE = (
    "redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', tonumber(ARGV[1]) - tonumber(ARGV[2]))\n"
    "if redis.call('ZCARD', KEYS[1]) < tonumber(ARGV[3]) then\n"
    "  redis.call('ZADD', KEYS[1], ARGV[1], ARGV[4])\n"
    "  return 1\n"
    "end\n"
    "return 0"
)

_local: "asyncio.Semaphore | None" = None


def _local_sem() -> asyncio.Semaphore:
    """Per-process fallback (Redis down). Lazily built inside the running loop."""
    global _local
    if _local is None:
        _local = asyncio.Semaphore(get_settings().llm_max_concurrency)
    return _local


@contextlib.asynccontextmanager
async def llm_slot():
    """Hold one service-wide LLM slot for the duration of the call (an async context manager)."""
    limit = get_settings().llm_max_concurrency
    client = get_redis(decode=True)
    if client is None:
        async with _local_sem():
            yield
        return
    member = uuid.uuid4().hex
    deadline = time.monotonic() + _ACQUIRE_TIMEOUT
    holding = False
    try:
        while True:
            try:
                ok = await client.eval(_ACQUIRE, 1, _KEY, time.time(), _LEASE_TTL, limit, member)
            except Exception:
                # Redis blip → bound THIS call with the local semaphore instead of blocking on Redis.
                async with _local_sem():
                    yield
                return
            if ok:
                holding = True
                break
            if time.monotonic() >= deadline:
                break  # budget stuck full → proceed without a slot rather than deadlock the pipeline
            await asyncio.sleep(_POLL)
        yield
    finally:
        if holding:
            with contextlib.suppress(Exception):
                await client.zrem(_KEY, member)
