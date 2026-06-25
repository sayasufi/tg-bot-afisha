"""Prefect flows — the orchestration layer that replaced Celery.

Each flow is a thin wrapper around an existing task implementation (the proven
``_*_impl`` functions); Prefect handles scheduling, retries, concurrency and the
run history/observability UI. The logic lives in ``tasks/*`` and is unchanged.
"""
from prefect import flow

from apps.worker.worker.tasks import dedup, digest, enrich, fetch, media, normalize, reminders, search_index

_RETRIES = 2
_RETRY_DELAY = 30  # seconds


# --- adstat (рекламный ресёрч каналов) ---------------------------------------

@flow(name="scrape-adstat", retries=1, retry_delay_seconds=120, timeout_seconds=3600, log_prints=True)
async def scrape_adstat():
    """Daily: лёгкий рефреш статистики активных targets — ТОЛЬКО Telemetr (быстро, без перегруза
    тариф-квоты и FlareSolverr). TGStat — для ручных прогонов по шорт-листу. No-op при ADSTAT_ENABLED=false."""
    import asyncio

    from apps.worker.worker.adstat.service import scrape

    rows = await asyncio.to_thread(scrape, None, False, ["telemetr"])
    ok = sum(1 for r in rows if not r.get("error"))
    return {"rows": len(rows), "ok": ok}


@flow(name="discover-adstat", retries=1, retry_delay_seconds=300, timeout_seconds=3600, log_prints=True)
async def discover_adstat():
    """Weekly: автопоиск новых афиша-каналов (Telemetr search по 16 городам) → targets + снимки."""
    import asyncio

    from apps.worker.worker.adstat.discover import discover

    rows = await asyncio.to_thread(discover, 3000, False)
    return {"found": len(rows)}


@flow(name="discover-telethon", retries=1, retry_delay_seconds=300, timeout_seconds=5400, log_prints=True)
async def discover_telethon_flow():
    """Weekly: расширить афиша-граф через рекомендации Telegram (Telethon, бесплатно) + метрики → adstat."""
    import asyncio

    from apps.worker.worker.adstat.telethon_src import discover_telethon

    n = await asyncio.to_thread(discover_telethon, None, 400, False)
    return {"written": n}


@flow(name="discover-telega", retries=1, retry_delay_seconds=300, timeout_seconds=5400, log_prints=True)
async def discover_telega_flow():
    """Weekly: каталог афиша-категории Telega.in (тысячи каналов) + реальные цены размещения → adstat."""
    import asyncio

    from apps.worker.worker.adstat.discover import discover_telega

    rows = await asyncio.to_thread(discover_telega, 52, 60, True, False)
    withp = sum(1 for r in rows if r.get("post_price"))
    return {"found": len(rows), "with_price": withp}


# --- fetch (sources) ---------------------------------------------------------

@flow(name="fetch-kudago", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=1800, log_prints=True)
async def fetch_kudago():
    return await fetch._fetch_kudago_impl()


@flow(name="fetch-kudago-full-scan", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=1800, log_prints=True)
async def fetch_kudago_full_scan():
    return await fetch._fetch_kudago_full_scan_impl()


@flow(name="fetch-yandex-afisha", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=1800, log_prints=True)
async def fetch_yandex_afisha():
    return await fetch._fetch_yandex_impl()


@flow(name="fetch-yandex-afisha-full-scan", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=1800, log_prints=True)
async def fetch_yandex_afisha_full_scan():
    return await fetch._fetch_yandex_full_scan_impl()


@flow(name="fetch-afisha-ru", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=1800, log_prints=True)
async def fetch_afisha_ru():
    return await fetch._fetch_afisha_impl()


@flow(name="fetch-afisha-ru-full-scan", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=1800, log_prints=True)
async def fetch_afisha_ru_full_scan():
    return await fetch._fetch_afisha_full_scan_impl()


@flow(name="fetch-timepad", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=1800, log_prints=True)
async def fetch_timepad():
    return await fetch._fetch_timepad_impl()


@flow(name="fetch-telegram-public", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=1800, log_prints=True)
async def fetch_telegram_public():
    return await fetch._fetch_telegram_impl()


@flow(name="prune-telegram-channels", retries=1, retry_delay_seconds=60, timeout_seconds=600, log_prints=True)
async def prune_telegram_channels():
    """Daily: deactivate channels that went dark (no posts in 60d / preview gone) so the active set stays live."""
    from pipeline.maintenance.telegram_health import prune_stale_channels
    return await prune_stale_channels()


@flow(name="sweep-stale-runs", retries=1, retry_delay_seconds=30, timeout_seconds=120, log_prints=True)
async def sweep_stale_runs():
    """Mark source_runs stuck in 'running' (a fetch orphaned by a deploy/crash between create_source_run
    and finish_source_run) as 'interrupted', so the run log doesn't fill with phantom in-flight rows."""
    from core.db.repositories.ingestion import sweep_stale_source_runs
    from core.db.session import WorkerAsyncSessionLocal
    async with WorkerAsyncSessionLocal() as db:
        return await sweep_stale_source_runs(db)


@flow(name="refresh-channel-subscribers", retries=1, retry_delay_seconds=60, timeout_seconds=600, log_prints=True)
async def refresh_channel_subscribers():
    """Daily: cache each active telegram channel's subscriber count (reach signal) from its t.me page."""
    from pipeline.maintenance.telegram_health import refresh_subscribers
    return await refresh_subscribers()


@flow(name="reindex-search", retries=1, retry_delay_seconds=30, timeout_seconds=600, log_prints=True)
async def reindex_search():
    """Refresh the Meilisearch typeahead index from active events (no-op when search is disabled)."""
    return await search_index._reindex_search_impl()


# --- pipeline (normalize -> enrich -> dedup) ---------------------------------

@flow(name="normalize-raw", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=600, log_prints=True)
async def normalize_raw():
    return await normalize._normalize_impl()


@flow(name="reprocess-changed", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=900, log_prints=True)
async def reprocess_changed():
    # Re-normalize structured-source raws whose content changed since first ingest (date shift / price
    # appears) so candidates + occurrences don't freeze forever.
    return await normalize._reprocess_changed_impl()


@flow(name="enrich-candidates", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=600, log_prints=True)
async def enrich_candidates():
    return await enrich._enrich_impl()


@flow(name="dedup-candidates", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=600, log_prints=True)
async def dedup_candidates():
    return await dedup._dedup_impl()


@flow(name="dedup-llm", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=600, log_prints=True)
async def dedup_llm():
    """LLM-assisted dedup of same-venue+same-time pairs the rules can't resolve
    (declension/initials/wrapper-word variants). Cached + blocked, so cheap in
    steady state."""
    return await dedup._dedup_llm_impl(apply=True)


@flow(name="dedup-fuzzy-llm", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=900, log_prints=True)
async def dedup_fuzzy_llm():
    """Daily: LLM-judge the REVIEW-tier fuzzy pairs (same venue+day, subset/high-ratio titles) and merge
    only high-confidence twins, so cross-source alt-naming dups self-heal instead of accumulating."""
    return await dedup._dedup_fuzzy_llm_impl(apply=True)


@flow(name="merge-duplicate-venues", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=600, log_prints=True)
def merge_duplicate_venues():
    return dedup._merge_venues_impl()


@flow(name="merge-duplicate-events", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=600, log_prints=True)
def merge_duplicate_events():
    return dedup._merge_events_impl()


@flow(name="expire-past-events", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=1200, log_prints=True)
def expire_past_events():
    """Lifecycle: first prune phantom future dates (a session a source no longer
    lists — the add-only upsert never deletes them), THEN expire events whose last
    live occurrence has passed and revive any that gained an upcoming one. Pruning
    before expiry means an event left with only a cancelled future date expires now
    instead of lingering until that phantom date passes."""
    from pipeline.maintenance.lifecycle import expire_past_events as _expire
    from pipeline.maintenance.prune_stale_occurrences import prune

    pruned = prune(apply=True)
    expired = _expire(apply=True)
    return {"pruned": pruned, "expired": expired}


@flow(name="resolve-afisha-dates", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=1200, log_prints=True)
async def resolve_afisha_dates():
    """Fill exact dates for afisha-ONLY multi-show events (Yandex covers the rest in
    bulk). Small, polite, idempotent — only the few hundred events not on Yandex."""
    from pipeline.maintenance.resolve_afisha_dates import resolve

    return await resolve(apply=True)


@flow(name="self-heal-dedup", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=1200, log_prints=True)
def self_heal_dedup():
    """Runs frequently to close the small window where two sources put one event
    at two not-yet-merged venue rows. Order matters: collapse the duplicate
    venues first, then the events now sitting at the shared venue. Idempotent and
    near-instant when there is nothing to merge."""
    venues = dedup._merge_venues_impl()
    events = dedup._merge_events_impl()
    # Then split events that (now) span >1 physical place — the per-session venue
    # assignment in resolve_afisha_dates makes a touring show one event with several
    # venues, which must become one event per venue. Idempotent once split.
    from pipeline.maintenance.resplit import resplit

    split = resplit(apply=True)
    return {"venues": venues, "events": events, "resplit": split}


# --- enrichment side-jobs ----------------------------------------------------

@flow(name="backfill-venues-osm", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=1200, log_prints=True)
async def backfill_venues_osm():
    return await enrich._backfill_venues_osm_impl()


@flow(name="resolve-venue-hours", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=1200, log_prints=True)
def resolve_venue_hours():
    return enrich._resolve_venue_hours_impl()


@flow(name="cache-event-images", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=1200, log_prints=True)
def cache_event_images():
    return media._cache_event_images_impl()


@flow(name="cache-telegram-images", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=1200, log_prints=True)
async def cache_telegram_images():
    """Lazily download photos only for telegram EVENTS (posts that survived the pipeline), via Telethon."""
    return await media._cache_telegram_images_impl()


# --- re-engagement (outbound) ------------------------------------------------

@flow(name="send-reminders", retries=1, retry_delay_seconds=15, timeout_seconds=300, log_prints=True)
async def send_reminders():
    """DM users a bot reminder for saved events whose start is near (the first outbound
    channel). Idempotent: each reminder row is stamped sent_at after a delivered/permanent
    Telegram response, so a retry never double-sends."""
    return await reminders._send_reminders_impl()


@flow(name="send-digest", retries=1, retry_delay_seconds=30, timeout_seconds=300, log_prints=True)
async def send_digest():
    """Weekly opt-in roundup DM: new at followed venues + the best of the coming weekend.
    Idempotent via a per-user last_digest_sent_at ledger (stamped on any Telegram response,
    checked against this ISO-week's start), so retries=1 is safe — a retry only re-sends to
    users a transient failure left unstamped, never a duplicate."""
    return await digest._send_digest_impl()
