"""Background data-maintenance jobs run by the Prefect flows (and as CLI):

- ``venues``      — fuzzy-merge duplicate venue rows.
- ``events``      — merge duplicate event rows (find_pairs / merge_duplicate_events).
- ``resplit``     — split events wrongly merged across physical places.
- ``lifecycle``   — expire events whose day has passed.
- ``healthcheck`` — assert the dedup invariants on live data.

Each module is runnable with ``python -m pipeline.maintenance.<name> [--dry-run]``.
"""
