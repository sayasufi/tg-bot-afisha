from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from apps.api.app.services.events_service import _redis_client
from apps.api.app.routes.events import router as events_router
from apps.api.app.routes.health import router as health_router
from apps.api.app.routes.intent import router as intent_router
from apps.api.app.routes.media import router as media_router
from apps.api.app.routes.places import router as places_router
from apps.api.app.routes.recommend import router as recommend_router
from apps.api.app.routes.share import router as share_router
from apps.api.app.routes.stats import router as stats_router
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
# NOTE: JSON responses are gzipped at the nginx edge (gzip_proxied any in the
# okrestmap site), NOT in-process — compressing the multi-MB map payload on the single
# event loop blocked the worker ~200ms/response. Keep compression off the Python path.


def _cors_origins() -> list[str]:
    """Explicit allowlist instead of '*'. '*' + allow_credentials is a CSRF/
    credential-theft footgun; the mini-app calls the API same-origin in prod so
    a tight list costs nothing."""
    raw = settings.cors_origins.strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    origins = {
        "https://okrestmap.ru",
        "https://www.okrestmap.ru",
        "https://tgbot-afisha.ru",
        "https://www.tgbot-afisha.ru",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    }
    if settings.telegram_webapp_url:
        origins.add(settings.telegram_webapp_url.rstrip("/"))
    return sorted(origins)


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    # No cookie/credential auth (the mini-app sends Telegram initData explicitly),
    # so credentials stay off — which is also what lets the allowlist be strict.
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


_RL_WINDOW = 60
_RL_MAX = 600  # requests per client IP per minute — well above a heavy session, blocks
# only volumetric abuse. Defense-in-depth behind the nginx edge (best-effort via Redis).


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS" or path in ("/v1/health", "/v1/ready"):
        return await call_next(request)
    client = _redis_client()
    if client is not None:
        # Real client IP — nginx sets X-Forwarded-For (the app sees only 127.0.0.1).
        fwd = request.headers.get("x-forwarded-for", "")
        ip = fwd.split(",")[0].strip() or (request.client.host if request.client else "?")
        try:
            key = f"rl:{ip}"
            n = await client.incr(key)
            if n == 1:
                await client.expire(key, _RL_WINDOW)
            if n > _RL_MAX:
                return Response(status_code=429, content=b'{"detail":"too many requests"}', media_type="application/json")
        except Exception:  # never block on the limiter
            pass
    return await call_next(request)


# Cache read endpoints so repeat loads come from the browser cache. Places are
# near-static (re-seeded rarely); the map/list changes slowly.
@app.middleware("http")
async def cache_control(request: Request, call_next):
    response = await call_next(request)
    if request.method == "GET" and response.status_code == 200:
        path = request.url.path
        if path.startswith("/v1/places"):
            response.headers.setdefault("Cache-Control", "public, max-age=3600, stale-while-revalidate=86400")
        elif path.startswith("/v1/recommendations"):
            # Per-user (personalised) — MUST stay private so no shared cache serves one
            # user's feed to another. The non-personal base is cached server-side instead.
            response.headers.setdefault("Cache-Control", "private, max-age=60, stale-while-revalidate=120")
        elif path.startswith("/v1/events/map"):
            response.headers.setdefault("Cache-Control", "public, max-age=30, stale-while-revalidate=120")
        elif path.startswith("/v1/search"):
            # Public typeahead — short edge/browser cache so repeated queries skip origin.
            response.headers.setdefault("Cache-Control", "public, max-age=60, stale-while-revalidate=120")
        elif path.startswith("/v1/events/"):
            response.headers.setdefault("Cache-Control", "public, max-age=300, stale-while-revalidate=600")
    return response


app.include_router(health_router)
app.include_router(events_router)
app.include_router(places_router)
app.include_router(telegram_router)
app.include_router(users_router)
app.include_router(media_router)
app.include_router(share_router)
app.include_router(recommend_router)
app.include_router(intent_router)
app.include_router(stats_router)
