from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from apps.api.services.events_service import _redis_client
from apps.api.routes.admin import router as admin_router
from apps.api.routes.admin_adstat import router as admin_adstat_router
from apps.api.routes.admin_analytics import router as admin_analytics_router
from apps.api.routes.admin_audit import router as admin_audit_router
from apps.api.routes.admin_broadcasts import router as admin_broadcasts_router
from apps.api.routes.admin_buys import router as admin_buys_router
from apps.api.routes.admin_funnel import router as admin_funnel_router
from apps.api.routes.admin_moderation import router as admin_moderation_router
from apps.api.routes.admin_channels import router as admin_channels_router
from apps.api.routes.admin_cities import router as admin_cities_router
from apps.api.routes.admin_dedup import router as admin_dedup_router
from apps.api.routes.admin_ops import router as admin_ops_router
from apps.api.routes.admin_events import router as admin_events_router
from apps.api.routes.admin_settings import router as admin_settings_router
from apps.api.routes.admin_sources import router as admin_sources_router
from apps.api.routes.admin_users import router as admin_users_router
from apps.api.routes.admin_venues import router as admin_venues_router
from apps.api.routes.auth import router as auth_router
from apps.api.routes.events import router as events_router
from apps.api.routes.go import router as go_router
from apps.api.routes.health import router as health_router
from apps.api.routes.intent import router as intent_router
from apps.api.routes.media import router as media_router
from apps.api.routes.places import router as places_router
from apps.api.routes.recommend import router as recommend_router
from apps.api.routes.share import router as share_router
from apps.api.routes.stats import router as stats_router
from apps.api.routes.suggest import router as suggest_router
from apps.api.routes.telegram import router as telegram_router
from apps.api.routes.users import router as users_router
from core.config.settings import get_settings
from core.logging.setup import setup_logging

from core.observability.sentry import init_sentry

settings = get_settings()
setup_logging(settings.log_level)
init_sentry("api")

# In prod the interactive docs / OpenAPI schema (/docs /redoc /openapi.json) are a needless
# surface-area leak — they enumerate every route and payload shape to anyone. Disable them on
# production hosts; keep them in dev/local where they're a useful tool.
_is_prod = settings.app_env == "production"
app = FastAPI(
    title="Afisha API",
    version="0.1.0",
    docs_url=None if _is_prod else "/docs",
    redoc_url=None if _is_prod else "/redoc",
    openapi_url=None if _is_prod else "/openapi.json",
)
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
_RL_MAX = 600  # general requests per client IP per minute — well above a heavy session, blocks
# only volumetric abuse. Defense-in-depth behind the nginx edge (best-effort via Redis).
# A stricter SECOND budget for the EXPENSIVE paths (a cache-miss = a live PostGIS join + a ~MB gzip on the
# event loop) — a legit session fires only a handful, so 120/min is generous but caps cache-miss abuse.
_RLX_MAX = 120
_EXPENSIVE_PREFIXES = ("/v1/events/map", "/v1/events/list", "/v1/recommendations")


async def _incr_over(client, key: str, limit: int) -> bool:
    n = await client.incr(key)
    if n == 1:
        await client.expire(key, _RL_WINDOW)
    return n > limit


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS" or path in ("/v1/health", "/v1/ready"):
        return await call_next(request)
    client = _redis_client()
    if client is not None:
        # Real client IP — nginx sets X-Forwarded-For (the app sees only the edge).
        fwd = request.headers.get("x-forwarded-for", "")
        ip = fwd.split(",")[0].strip() or (request.client.host if request.client else "?")
        try:
            limited = await _incr_over(client, f"rl:{ip}", _RL_MAX)
            if not limited and any(path.startswith(p) for p in _EXPENSIVE_PREFIXES):
                limited = await _incr_over(client, f"rlx:{ip}", _RLX_MAX)
            if limited:
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
app.include_router(go_router)
app.include_router(places_router)
app.include_router(telegram_router)
app.include_router(users_router)
app.include_router(suggest_router)
app.include_router(media_router)
app.include_router(share_router)
app.include_router(recommend_router)
app.include_router(intent_router)
app.include_router(auth_router)
app.include_router(stats_router)
app.include_router(admin_router)
app.include_router(admin_channels_router)
app.include_router(admin_sources_router)
app.include_router(admin_broadcasts_router)
app.include_router(admin_events_router)
app.include_router(admin_analytics_router)
app.include_router(admin_venues_router)
app.include_router(admin_dedup_router)
app.include_router(admin_settings_router)
app.include_router(admin_users_router)
app.include_router(admin_cities_router)
app.include_router(admin_audit_router)
app.include_router(admin_moderation_router)
app.include_router(admin_adstat_router)
app.include_router(admin_ops_router)
app.include_router(admin_buys_router)
app.include_router(admin_funnel_router)
