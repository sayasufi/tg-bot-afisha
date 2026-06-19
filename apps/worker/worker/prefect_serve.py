"""Prefect runner — schedules and executes all flows in one long-running process
(replaces the Celery worker + beat + RedBeat). ``serve`` registers each flow as a
scheduled deployment against the Prefect server (for the UI / run history) and runs
due flow runs in-process.

Each deployment gets ``concurrency_limit=1`` so a run never overlaps itself — the
equivalent of the old ``single_instance`` Redis lock, but enforced + visible in the
Prefect UI.
"""
from prefect import serve

from apps.worker.worker import flows

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
    (flows.fetch_telegram_public, 180),
    (flows.normalize_raw, 60),
    (flows.enrich_candidates, 60),
    (flows.dedup_candidates, 60),
    # Self-heal venue+event dups every 15 min (ordered: venues then events) so the
    # cross-venue-row case can't linger. Write-time dedup already handles the
    # common same-venue case immediately.
    (flows.self_heal_dedup, 900),
    # Primary LLM-dedup is now at WRITE TIME (dedup_and_upsert_event). This is just a
    # daily safety net for the rare post-hoc collision: two existing events that come
    # to share a venue+time only after a venue merge (so neither was re-ingested).
    (flows.dedup_llm, 86400),
    (flows.expire_past_events, 3600),  # hourly — drop events whose day has passed
    (flows.resolve_afisha_dates, 21600),  # 6h — dates for the few afisha-only multi-show events
    (flows.backfill_venues_osm, 86400),
    (flows.resolve_venue_hours, 600),
    (flows.cache_event_images, 120),
    # Re-engagement: DM saved-event reminders as they come due. Cheap (a partial-index
    # scan + a few sends), so run it often enough that "~2h before" is accurate.
    (flows.send_reminders, 60),
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
