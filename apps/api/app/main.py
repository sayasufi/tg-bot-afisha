from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from apps.api.app.routes.events import router as events_router
from apps.api.app.routes.health import router as health_router
from apps.api.app.routes.media import router as media_router
from apps.api.app.routes.places import router as places_router
from apps.api.app.routes.telegram import router as telegram_router
from apps.api.app.routes.users import router as users_router
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
# Compress JSON responses (map/places payloads are tens of KB → a few KB).
app.add_middleware(GZipMiddleware, minimum_size=600)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Cache read endpoints so repeat loads come from the browser cache. Places are
# near-static (re-seeded rarely); the map/list changes slowly.
@app.middleware("http")
async def cache_control(request: Request, call_next):
    response = await call_next(request)
    if request.method == "GET" and response.status_code == 200:
        path = request.url.path
        if path.startswith("/v1/places"):
            response.headers.setdefault("Cache-Control", "public, max-age=3600, stale-while-revalidate=86400")
        elif path.startswith("/v1/events/map"):
            response.headers.setdefault("Cache-Control", "public, max-age=30, stale-while-revalidate=120")
        elif path.startswith("/v1/events/"):
            response.headers.setdefault("Cache-Control", "public, max-age=300, stale-while-revalidate=600")
    return response


app.include_router(health_router)
app.include_router(events_router)
app.include_router(places_router)
app.include_router(telegram_router)
app.include_router(users_router)
app.include_router(media_router)
