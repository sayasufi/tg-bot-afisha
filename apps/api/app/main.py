from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.app.routes.events import router as events_router
from apps.api.app.routes.health import router as health_router
from apps.api.app.routes.telegram import router as telegram_router
from core.config.settings import get_settings
from core.logging.setup import setup_logging

try:
    import sentry_sdk
except Exception:  # pragma: no cover
    sentry_sdk = None

settings = get_settings()
setup_logging(settings.log_level)
if settings.sentry_dsn and sentry_sdk is not None:
    sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.app_env)

app = FastAPI(title="Afisha API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(events_router)
app.include_router(telegram_router)
