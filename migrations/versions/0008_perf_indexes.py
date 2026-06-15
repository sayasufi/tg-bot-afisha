"""performance indexes for pipeline queues, dedup, and map queries

Revision ID: 0008_perf_indexes
Revises: 0007_venue_hours
Create Date: 2026-06-15
"""
from alembic import op

revision = "0008_perf_indexes"
down_revision = "0007_venue_hours"
branch_labels = None
depends_on = None

# (name, table, columns) — created IF NOT EXISTS so the migration is idempotent.
_INDEXES = [
    # normalize anti-join (raw -> candidate) and dedup lookups by raw_id
    ("ix_event_candidates_raw_id", "events.event_candidates", "raw_id"),
    # enrich queue: candidates with venue_id IS NULL
    ("ix_event_candidates_venue_id", "events.event_candidates", "venue_id"),
    # FK index for "remaining links" count + event_detail joins (raw_id already unique)
    ("ix_event_sources_event_id", "events.event_sources", "event_id"),
    # map_events / event_detail outerjoin occurrences -> venues
    ("ix_event_occurrences_venue_id", "events.event_occurrences", "venue_id"),
    # map_events filter: status = 'active' AND category IN (...)
    ("ix_events_status_category", "events.events", "status, category"),
]


def upgrade() -> None:
    for name, table, cols in _INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols})")


def downgrade() -> None:
    for name, _table, _cols in _INDEXES:
        op.execute(f"DROP INDEX IF EXISTS events.{name}")
