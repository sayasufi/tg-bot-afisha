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
    ],
)

celery_app.conf.task_routes = {
    "apps.worker.worker.tasks.fetch.*": {"queue": "fetch"},
    "apps.worker.worker.tasks.normalize.*": {"queue": "normalize"},
    "apps.worker.worker.tasks.enrich.*": {"queue": "enrich"},
    "apps.worker.worker.tasks.dedup.*": {"queue": "dedup"},
}

celery_app.conf.beat_schedule = {
    "fetch-timepad": {
        "task": "apps.worker.worker.tasks.fetch.fetch_timepad",
        "schedule": 300.0,
    },
    "fetch-telegram-public": {
        "task": "apps.worker.worker.tasks.fetch.fetch_telegram_public",
        "schedule": 180.0,
    },
    "fetch-forward-inbox": {
        "task": "apps.worker.worker.tasks.fetch.fetch_forward_inbox",
        "schedule": 60.0,
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
}

celery_app.conf.task_default_retry_delay = 10
celery_app.conf.task_acks_late = True
