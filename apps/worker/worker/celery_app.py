from celery import Celery

from core.config.settings import get_settings

settings = get_settings()

celery_app = Celery(
    "afisha_worker",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "apps.worker.worker.tasks.fetch",
        "apps.worker.worker.tasks.normalize",
        "apps.worker.worker.tasks.enrich",
        "apps.worker.worker.tasks.dedup",
        "apps.worker.worker.tasks.seed",
        "apps.worker.worker.tasks.media",
    ],
)

celery_app.conf.task_routes = {
    "apps.worker.worker.tasks.fetch.*": {"queue": "fetch"},
    "apps.worker.worker.tasks.normalize.*": {"queue": "normalize"},
    "apps.worker.worker.tasks.enrich.*": {"queue": "enrich"},
    "apps.worker.worker.tasks.dedup.*": {"queue": "dedup"},
    "apps.worker.worker.tasks.seed.*": {"queue": "enrich"},
    "apps.worker.worker.tasks.media.*": {"queue": "enrich"},
}

celery_app.conf.beat_schedule = {
    "fetch-kudago": {
        "task": "apps.worker.worker.tasks.fetch.fetch_kudago",
        "schedule": 300.0,
    },
    "fetch-kudago-full-scan-daily": {
        "task": "apps.worker.worker.tasks.fetch.fetch_kudago_full_scan",
        "schedule": 86400.0,
    },
    "fetch-yandex-afisha": {
        "task": "apps.worker.worker.tasks.fetch.fetch_yandex_afisha",
        "schedule": 300.0,
    },
    "fetch-yandex-afisha-full-scan": {
        "task": "apps.worker.worker.tasks.fetch.fetch_yandex_afisha_full_scan",
        "schedule": 43200.0,
    },
    "fetch-afisha-ru": {
        "task": "apps.worker.worker.tasks.fetch.fetch_afisha_ru",
        "schedule": 300.0,
    },
    "fetch-afisha-ru-full-scan": {
        "task": "apps.worker.worker.tasks.fetch.fetch_afisha_ru_full_scan",
        "schedule": 43200.0,
    },
    "fetch-telegram-public": {
        "task": "apps.worker.worker.tasks.fetch.fetch_telegram_public",
        "schedule": 180.0,
    },
    "normalize-raw": {
        "task": "apps.worker.worker.tasks.normalize.normalize_raw_events",
        "schedule": 60.0,
    },
    "enrich-candidates": {
        "task": "apps.worker.worker.tasks.enrich.enrich_candidates",
        "schedule": 60.0,
    },
    "dedup-candidates": {
        "task": "apps.worker.worker.tasks.dedup.dedup_candidates",
        "schedule": 60.0,
    },
    "backfill-venues-osm": {
        "task": "apps.worker.worker.tasks.enrich.backfill_venues_osm",
        "schedule": 86400.0,
    },
    "resolve-venue-hours": {
        "task": "apps.worker.worker.tasks.enrich.resolve_venue_hours",
        "schedule": 600.0,
    },
    "cache-event-images": {
        "task": "apps.worker.worker.tasks.media.cache_event_images",
        "schedule": 120.0,
    },
}

celery_app.conf.task_default_retry_delay = 10
celery_app.conf.task_acks_late = True
# Bound every task so a hung upstream (geocoder / LLM / image fetch) can't hold a
# worker slot forever and starve fetch/normalize/dedup. Soft limit raises
# SoftTimeLimitExceeded (catchable for cleanup); hard limit kills the worker.
celery_app.conf.task_soft_time_limit = 600
celery_app.conf.task_time_limit = 900

# RedBeat: store the beat schedule in Redis behind a distributed lock so the
# scheduler is no longer a single hard-wired process — multiple beat replicas can
# run and exactly one fires each tick (removes the beat SPOF when scaling out).
celery_app.conf.redbeat_redis_url = settings.redis_url
celery_app.conf.beat_scheduler = "redbeat.RedBeatScheduler"
celery_app.conf.redbeat_lock_timeout = 900
