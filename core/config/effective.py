"""Live-override слой поверх замороженного @lru_cache get_settings().

get_effective(key, default, db=None) → ref.app_settings[key].value, иначе `default`.
ТОЛЬКО ASYNC (каждая выставляемая настройка читается из async-кода) — никакого sync-моста
через asyncio.run(). Fail-open: любая проблема с БД возвращает `default`, никогда не бросает и
не блокирует горячий путь. In-proc TTL-кэш (БЕЗ Redis) ограничивает нагрузку на БД; все процессы
сходятся к новому значению за _TTL секунд. Гард типа на ЧТЕНИИ отвергает кривой override
(например JSON-строку "false") и откатывается к `default`.

Горячий путь (search) передаёт СВОЮ сессию запроса (db=self.db) — мы НИКОГДА не открываем 2-е
пуловое соединение внутри запроса, который уже держит одно (иначе дедлок пула под нагрузкой).
Холодные воркер-пути (afisha/reindex, ~раз в час) идут через NullPool WorkerAsyncSessionLocal.
"""
import logging
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.session import WorkerAsyncSessionLocal

log = logging.getLogger(__name__)

_TTL = 15.0       # секунд; потолок сходимости каждого процесса после записи
_MAX = 256        # жёсткий предел кэша (ключей мало; защита от неограниченного роста)
_MISS = object()  # негативный кэш: «строки-override нет» (чтобы горячий путь не бил в БД зря)

_cache: dict[str, tuple[Any, float]] = {}  # key -> (value|_MISS, expires_at_monotonic)


def _typed(value: Any, default: Any) -> Any:
    """Сверить override с типом default; несоответствие → откат к default.

    JSONB хранит произвольный JSON; неверный тип (строка "false", null) НЕ должен испортить ветку.
    bool проверяем первым — он подкласс int.
    """
    if isinstance(default, bool):
        return value if isinstance(value, bool) else default
    if isinstance(default, int):
        return value if (isinstance(value, int) and not isinstance(value, bool)) else default
    if isinstance(default, float):
        return value if (isinstance(value, (int, float)) and not isinstance(value, bool)) else default
    if isinstance(default, str):
        return value if isinstance(value, str) else default
    return value


async def _read_db(key: str, db: AsyncSession | None) -> Any:
    """ref.app_settings[key].value или _MISS. Переиспользует `db` если дан (горячий путь — сессия
    запроса, без 2-го пулового соединения), иначе loop-safe NullPool-сессия. Никогда не бросает."""
    sql = text("SELECT value FROM ref.app_settings WHERE key = :k")
    try:
        if db is not None:
            row = (await db.execute(sql, {"k": key})).first()
        else:
            async with WorkerAsyncSessionLocal() as s:
                row = (await s.execute(sql, {"k": key})).first()
        return row[0] if row else _MISS
    except Exception:
        log.debug("get_effective db read failed for %s", key, exc_info=True)
        return _MISS


async def get_effective(key: str, default: Any, db: AsyncSession | None = None) -> Any:
    """Резолв живой настройки: override если есть и тип верный, иначе `default`. Никогда не бросает."""
    hit = _cache.get(key)
    if hit is not None and time.monotonic() < hit[1]:
        v = hit[0]
        return default if v is _MISS else _typed(v, default)

    v = await _read_db(key, db)
    if len(_cache) >= _MAX:
        _cache.clear()
    _cache[key] = (v, time.monotonic() + _TTL)
    return default if v is _MISS else _typed(v, default)


def bust(key: str) -> None:
    """Сбросить локальный кэш после записи (записавший процесс свеж мгновенно; остальные сходятся за
    _TTL). Sync, best-effort, никогда не бросает."""
    _cache.pop(key, None)
