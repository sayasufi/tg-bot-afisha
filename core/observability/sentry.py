"""Общий Sentry-init — вызывать ОДИН раз в каждом entrypoint (api/bot/worker), чтобы тихие падения в
боте и воркере (рассылки, инжест, нормализация — где как раз чаще всего что-то молча ломается) попадали в
Sentry, а не только в логи, которые никто не читает в реальном времени. No-op, если SENTRY_DSN не задан.
"""
import logging

try:
    import sentry_sdk
except Exception:  # pragma: no cover
    sentry_sdk = None

from core.config.settings import get_settings

log = logging.getLogger(__name__)


def init_sentry(component: str) -> None:
    """component — 'api' | 'bot' | 'worker'; тегируется в каждом событии, чтобы различать источник."""
    settings = get_settings()
    if not settings.sentry_dsn or sentry_sdk is None:
        return
    sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.app_env)
    sentry_sdk.set_tag("component", component)
    log.info("sentry initialised for component=%s", component)
