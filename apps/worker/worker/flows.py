"""Prefect flows — the orchestration layer that replaced Celery.

Each flow is a thin wrapper around an existing task implementation (the proven
``_*_impl`` functions); Prefect handles scheduling, retries, concurrency and the
run history/observability UI. The logic lives in ``tasks/*`` and is unchanged.
"""
from prefect import flow

from apps.worker.worker.tasks import dedup, enrich, fetch, media, normalize

_RETRIES = 2
_RETRY_DELAY = 30  # seconds


# --- fetch (sources) ---------------------------------------------------------

@flow(name="fetch-kudago", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, log_prints=True)
async def fetch_kudago():
    return await fetch._fetch_kudago_impl()


@flow(name="fetch-kudago-full-scan", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, log_prints=True)
async def fetch_kudago_full_scan():
    return await fetch._fetch_kudago_full_scan_impl()


@flow(name="fetch-yandex-afisha", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, log_prints=True)
async def fetch_yandex_afisha():
    return await fetch._fetch_yandex_impl()


@flow(name="fetch-yandex-afisha-full-scan", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, log_prints=True)
async def fetch_yandex_afisha_full_scan():
    return await fetch._fetch_yandex_full_scan_impl()


@flow(name="fetch-afisha-ru", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, log_prints=True)
async def fetch_afisha_ru():
    return await fetch._fetch_afisha_impl()


@flow(name="fetch-afisha-ru-full-scan", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, log_prints=True)
async def fetch_afisha_ru_full_scan():
    return await fetch._fetch_afisha_full_scan_impl()


@flow(name="fetch-telegram-public", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, log_prints=True)
async def fetch_telegram_public():
    return await fetch._fetch_telegram_impl()


# --- pipeline (normalize -> enrich -> dedup) ---------------------------------

@flow(name="normalize-raw", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, log_prints=True)
async def normalize_raw():
    return await normalize._normalize_impl()


@flow(name="enrich-candidates", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, log_prints=True)
async def enrich_candidates():
    return await enrich._enrich_impl()


@flow(name="dedup-candidates", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, log_prints=True)
async def dedup_candidates():
    return await dedup._dedup_impl()


@flow(name="merge-duplicate-venues", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, log_prints=True)
def merge_duplicate_venues():
    return dedup._merge_venues_impl()


@flow(name="merge-duplicate-events", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, log_prints=True)
def merge_duplicate_events():
    return dedup._merge_events_impl()


@flow(name="expire-past-events", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, log_prints=True)
def expire_past_events():
    """Lifecycle: expire events whose last occurrence day has passed, revive any
    that gained an upcoming one, so the app never shows what already happened."""
    from pipeline.maintenance.lifecycle import expire_past_events as _run

    return _run(apply=True)


@flow(name="resolve-afisha-dates", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, log_prints=True)
async def resolve_afisha_dates():
    """Fill exact dates for afisha-ONLY multi-show events (Yandex covers the rest in
    bulk). Small, polite, idempotent — only the few hundred events not on Yandex."""
    from pipeline.maintenance.resolve_afisha_dates import resolve

    return await resolve(apply=True)


@flow(name="self-heal-dedup", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, log_prints=True)
def self_heal_dedup():
    """Runs frequently to close the small window where two sources put one event
    at two not-yet-merged venue rows. Order matters: collapse the duplicate
    venues first, then the events now sitting at the shared venue. Idempotent and
    near-instant when there is nothing to merge."""
    venues = dedup._merge_venues_impl()
    events = dedup._merge_events_impl()
    return {"venues": venues, "events": events}


# --- enrichment side-jobs ----------------------------------------------------

@flow(name="backfill-venues-osm", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, log_prints=True)
async def backfill_venues_osm():
    return await enrich._backfill_venues_osm_impl()


@flow(name="resolve-venue-hours", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, log_prints=True)
def resolve_venue_hours():
    return enrich._resolve_venue_hours_impl()


@flow(name="cache-event-images", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, log_prints=True)
def cache_event_images():
    return media._cache_event_images_impl()
