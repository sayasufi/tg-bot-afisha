"""Single-instance guard for beat-driven Celery tasks.

The beat schedule is dense (normalize/enrich/dedup every 60s); if a run takes longer
than its interval, the next tick would start a second instance that races the first on
the same queue rows (double-processing, duplicate candidates). This wraps a task so only
ONE instance runs at a time — a second tick is skipped while the first holds the lock.
The Redis lock auto-expires after `timeout`, so a crashed task can never deadlock the
schedule. (At multi-worker scale, replace with row-level FOR UPDATE SKIP LOCKED.)
"""
import functools
import logging

import redis

from core.config.settings import get_settings

logger = logging.getLogger(__name__)

_client: redis.Redis | None = None


def _redis() -> redis.Redis | None:
    global _client
    if _client is None:
        try:
            _client = redis.from_url(get_settings().redis_url, socket_timeout=2, socket_connect_timeout=2)
        except Exception:  # pragma: no cover
            logger.warning("tasklock_redis_init_failed", exc_info=True)
            return None
    return _client


def single_instance(name: str, timeout: int = 1800):
    """Decorator: run at most one instance of the task at a time (skip if already running)."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            client = _redis()
            if client is None:  # cache/lock unavailable -> don't block real work
                return fn(*args, **kwargs)
            lock = client.lock(f"tasklock:{name}", timeout=timeout, blocking=False)
            try:
                acquired = lock.acquire(blocking=False)
            except Exception:
                logger.debug("tasklock_acquire_failed name=%s", name, exc_info=True)
                return fn(*args, **kwargs)
            if not acquired:
                return {"skipped": "locked", "task": name}
            try:
                return fn(*args, **kwargs)
            finally:
                try:
                    lock.release()
                except Exception:  # lock may have expired during a long run
                    pass

        return wrapper

    return decorator
