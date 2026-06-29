"""The service-wide LLM limiter must actually BOUND concurrency, and never block LLM work when Redis
misbehaves. These exercise the degraded paths deterministically (no Redis needed)."""
import asyncio

import core.services.llm_limiter as lim


def _run_workers(n: int, hold: float = 0.01) -> int:
    """Run n coroutines through llm_slot concurrently; return the peak simultaneous holders."""
    state = {"cur": 0, "max": 0}

    async def worker():
        async with lim.llm_slot():
            state["cur"] += 1
            state["max"] = max(state["max"], state["cur"])
            await asyncio.sleep(hold)
            state["cur"] -= 1

    async def main():
        await asyncio.gather(*[worker() for _ in range(n)])

    asyncio.run(main())
    return state["max"]


def test_bounds_concurrency_when_redis_absent(monkeypatch):
    monkeypatch.setattr(lim, "get_redis", lambda **kw: None)  # force the local-semaphore fallback
    lim._local = None  # fresh semaphore inside this test's loop
    try:
        limit = lim._current_limit()  # the cap that actually applies now (day vs night), so it's deterministic
        peak = _run_workers(limit * 3)
        assert peak <= limit  # never exceeds the budget
        assert peak >= min(limit, 5)  # and it parallelises (doesn't serialise to 1)
    finally:
        lim._local = None


def test_redis_error_degrades_to_local_not_block(monkeypatch):
    class _BadRedis:
        async def eval(self, *a, **k):
            raise RuntimeError("redis down")

        async def zrem(self, *a, **k):
            pass

    monkeypatch.setattr(lim, "get_redis", lambda **kw: _BadRedis())
    lim._local = None
    try:
        peak = _run_workers(10)
        assert 1 <= peak <= lim._current_limit()  # ran (no deadlock), still bounded
    finally:
        lim._local = None
