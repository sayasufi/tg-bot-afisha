"""events.event_occurrences: unique (event_id, date_start, venue_id)

Prevents duplicate occurrences when the ingestion pipeline is re-run.
venue_id is nullable, so the index uses COALESCE so venue-less events still
collapse to one row per (event, start).

Revision ID: 0005_occurrence_unique
Revises: 0004_user_profile
Create Date: 2026-06-13
"""

from alembic import op


revision = "0005_occurrence_unique"
down_revision = "0004_user_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Collapse any pre-existing duplicates, keeping the lowest occurrence_id.
    op.execute(
        """
        DELETE FROM events.event_occurrences a
        USING events.event_occurrences b
        WHERE a.occurrence_id > b.occurrence_id
          AND a.event_id = b.event_id
          AND a.date_start = b.date_start
          AND COALESCE(a.venue_id, -1) = COALESCE(b.venue_id, -1)
        """
    )
    # 2) Enforce uniqueness going forward.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_occurrence_event_start_venue
        ON events.event_occurrences (event_id, date_start, COALESCE(venue_id, -1))
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS events.uq_occurrence_event_start_venue")
