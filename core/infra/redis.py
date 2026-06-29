"""One shared, memoized async Redis client per decode mode.

The map cache stores GZIPPED bytes (decode_responses=False); recommend stores text
(decode_responses=True). Both used to copy-paste their own lazy-init + swallow-and-disable
logic — this is the single definition. Best-effort: returns None (and disables) if the
client can't be built, so callers degrade gracefully.
"""
import redis.asyncio as aioredis

from core.config.settings import get_settings

_clients: dict[bool, "aioredis.Redis | None"] = {}
_off = False


def get_redis(*, decode: bool) -> "aioredis.Redis | None":
    global _off
    if _off:
        return None
    if decode not in _clients:
        try:
            _clients[decode] = aioredis.from_url(
                get_settings().redis_url,
                decode_responses=decode,
                socket_timeout=0.5,
                socket_connect_timeout=0.5,
            )
        except Exception:  # pragma: no cover - cache is best-effort
            _off = True
            return None
    return _clients[decode]
