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
    (flows.fetch_kudago_full_scan, 86400),
    (flows.fetch_yandex_afisha, 300),
    (flows.fetch_yandex_afisha_full_scan, 43200),
    (flows.fetch_afisha_ru, 300),
    (flows.fetch_afisha_ru_full_scan, 43200),
    (flows.fetch_telegram_public, 180),
    (flows.normalize_raw, 60),
    (flows.enrich_candidates, 60),
    (flows.dedup_candidates, 60),
    (flows.merge_duplicate_venues, 21600),  # 6h — collapse near-dup venues
    (flows.backfill_venues_osm, 86400),
    (flows.resolve_venue_hours, 600),
    (flows.cache_event_images, 120),
]


def main() -> None:
    deployments = [
        fl.to_deployment(name=fl.name, interval=interval, concurrency_limit=1)
        for fl, interval in _SCHEDULE
    ]
    serve(*deployments, limit=10)


if __name__ == "__main__":
    main()
