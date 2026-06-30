"""Prefect runner — schedules and executes all flows in one long-running process
(replaces the Celery worker + beat + RedBeat). ``serve`` registers each flow as a
scheduled deployment against the Prefect server (for the UI / run history) and runs
due flow runs in-process.

Each deployment gets ``concurrency_limit=1`` so a run never overlaps itself — the
equivalent of the old ``single_instance`` Redis lock, but enforced + visible in the
Prefect UI.
"""
from prefect import serve

from apps.worker import flows

# (flow, interval_seconds) — mirrors the former Celery beat schedule.
_SCHEDULE = [
    (flows.fetch_kudago, 300),
    # The incremental -publication_date cursor wraps on 404 and re-reads the head, so
    # it surfaces few upcoming events; the dates-ordered full-scan is what actually
    # walks the upcoming window. Run it every 6h (was 24h) to cut KudaGo staleness
    # ~24h→~6h. Kept at 6h (not more frequent) because the worker is concurrency_limit=1
    # and a deep scan must not starve the normalize→enrich→dedup pipeline.
    (flows.fetch_kudago_full_scan, 21600),
    (flows.fetch_yandex_afisha, 300),
    (flows.fetch_yandex_afisha_full_scan, 43200),
    (flows.fetch_afisha_ru, 300),
    (flows.fetch_afisha_ru_full_scan, 43200),
    # Timepad is one curated full-scan (no incremental cursor); the whitelisted+collapsed set is small
    # (~hundreds), so every 30 min keeps it fresh without starving the concurrency-1 pipeline. No-op
    # until TIMEPAD_TOKEN is set.
    (flows.fetch_timepad, 1800),
    (flows.fetch_telegram_public, 180),
    # Daily health-check: retire venue channels that went dark (closed/moved/last post >60d ago) so the
    # active set never silently rots (venues do close — Powerhouse, Mutabor→Arma, a 2022-dead fest).
    (flows.prune_telegram_channels, 86400),
    # Daily: cache each active channel's subscriber count (reach signal) in ref.telegram_channels.
    (flows.refresh_channel_subscribers, 86400),
    # Every 30 min: mark source_runs orphaned by a deploy/crash (stuck in 'running') as 'interrupted',
    # so the run log doesn't accumulate phantom in-flight rows. The 2h threshold is well above any run.
    (flows.sweep_stale_runs, 1800),
    # Keep the Meilisearch typeahead index fresh (no-op until MEILI_SEARCH_ENABLED). Cheap full
    # reindex at this scale; the atomic swap means search never sees an empty index.
    (flows.reindex_search, 120),
    # Кастомные рассылки: каждые 5 мин подхватываем дозревшие кампании (now/at_utc). Ledger = идемпотентность.
    (flows.dispatch_broadcasts, 300),
    # Реальные подписчики adstat-каналов из t.me (точнее каталога Telega) — батч раз в 6ч, ротация по 600.
    (flows.refresh_adstat_subs, 21600),
    # Telethon-добор точных метрик для on-topic каналов без t.me-превью — раз в сутки, малый батч (флуд-лимиты).
    (flows.enrich_adstat_telethon, 86400),
    # LLM-классификация релевантности каналов (точнее кейвордов) — раз в сутки, инкрементально по 400.
    (flows.classify_adstat_llm, 86400),
    (flows.normalize_raw, 60),
    (flows.enrich_candidates, 60),
    (flows.dedup_candidates, 60),
    # Re-normalize structured-source raws whose content changed since first ingest (a date shifted as
    # old ones passed, a price appeared) so candidates + occurrences don't freeze at first-seen state.
    (flows.reprocess_changed, 300),
    # Self-heal venue+event dups every 15 min (ordered: venues then events) so the
    # cross-venue-row case can't linger. Write-time dedup already handles the
    # common same-venue case immediately.
    (flows.self_heal_dedup, 900),
    # Primary LLM-dedup is now at WRITE TIME (dedup_and_upsert_event). This is just a
    # daily safety net for the rare post-hoc collision: two existing events that come
    # to share a venue+time only after a venue merge (so neither was re-ingested).
    (flows.dedup_llm, 86400),
    # Daily LLM pass over the review-tier fuzzy pairs (same venue+day alt-naming) so they self-heal.
    # Cached verdicts (incl. negatives) keep steady-state runs near-free.
    (flows.dedup_fuzzy_llm, 86400),
    (flows.expire_past_events, 3600),  # hourly — drop events whose day has passed
    (flows.resolve_afisha_dates, 21600),  # 6h — dates for the few afisha-only multi-show events
    (flows.backfill_venues_osm, 86400),
    (flows.correct_venue_coords, 86400),  # daily — re-geocode 'source' venues, fix pins that landed off the address
    (flows.resolve_venue_hours, 600),
    (flows.cache_event_images, 120),
    # Lazily pull photos only for telegram EVENTS (the connector no longer downloads one per post).
    (flows.cache_telegram_images, 180),
    # Re-engagement: DM saved-event reminders as they come due. Cheap (a partial-index
    # scan + a few sends), so run it often enough that "~2h before" is accurate.
    (flows.send_reminders, 60),
    # D1-нудж: первый возвратный DM тем, кто открыл апп ~сутки назад и ничего не сохранил (молчание до пятницы).
    (flows.welcome_nudge, 1800),
    # Рекламный ресёрч каналов (схема adstat). Discovery ЕЖЕДНЕВНО (ловит новые афиша-каналы по мере
    # появления: Telemetr-поиск по 16 городам, Telega-каталог, Telethon-граф рекомендаций) + лёгкий рефреш
    # статистики ежедневно (Telemetr). concurrency_limit=1 → не пересекаются, идут по очереди. No-op, пока
    # ADSTAT_ENABLED=false.
    (flows.discover_adstat, 86400),
    (flows.discover_telega_flow, 86400),
    (flows.discover_telethon_flow, 86400),
    (flows.enrich_shortlist_prices_flow, 86400),  # добор цен telega по топ-афише → CPM → «брать»
    (flows.scrape_adstat, 86400),
]


def main() -> None:
    deployments = [
        fl.to_deployment(name=fl.name, interval=interval, concurrency_limit=1)
        for fl, interval in _SCHEDULE
    ]
    # Weekly digest — a CRON, not an interval, so it lands a fixed local time (the weekend-
    # planning moment) instead of "1 week after this process last restarted". Fri 07:00 UTC =
    # 10:00 MSK (MSK is a fixed UTC+3, no DST), so a plain UTC cron is stable year-round.
    deployments.append(
        flows.send_digest.to_deployment(name=flows.send_digest.name, cron="0 7 * * 5", concurrency_limit=1)
    )
    serve(*deployments, limit=10)


if __name__ == "__main__":
    main()
