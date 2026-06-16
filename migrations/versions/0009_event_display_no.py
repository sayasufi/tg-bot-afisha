"""stable per-event display number (public "MSK-04PN" codes)

Revision ID: 0009_event_display_no
Revises: 0008_perf_indexes
Create Date: 2026-06-17

Adds events.display_no: a unique, monotonic sequence assigned once per event and
encoded into the public Crockford-base32 code shown in the app (and reserved for a
future /e/<code> short link). Backfilled by created_at so existing events keep a
stable number; new events draw from the sequence by column default.
"""
from alembic import op

revision = "0009_event_display_no"
down_revision = "0008_perf_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS events.events_display_no_seq")
    op.execute("ALTER TABLE events.events ADD COLUMN IF NOT EXISTS display_no BIGINT")
    # Backfill only the not-yet-numbered rows, in a STABLE order so a re-run never
    # reshuffles already-published numbers.
    op.execute(
        "UPDATE events.events e SET display_no = sub.rn FROM ("
        "  SELECT event_id, row_number() OVER (ORDER BY created_at, event_id) AS rn"
        "  FROM events.events"
        ") sub WHERE e.event_id = sub.event_id AND e.display_no IS NULL"
    )
    # Point the sequence past the highest backfilled value (is_called=false → the
    # next nextval RETURNS this value), so new events continue without collision.
    op.execute(
        "SELECT setval('events.events_display_no_seq',"
        " COALESCE((SELECT max(display_no) FROM events.events), 0) + 1, false)"
    )
    op.execute(
        "ALTER TABLE events.events ALTER COLUMN display_no"
        " SET DEFAULT nextval('events.events_display_no_seq')"
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_events_display_no ON events.events (display_no)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS events.ux_events_display_no")
    op.execute("ALTER TABLE events.events ALTER COLUMN display_no DROP DEFAULT")
    op.execute("ALTER TABLE events.events DROP COLUMN IF EXISTS display_no")
    op.execute("DROP SEQUENCE IF EXISTS events.events_display_no_seq")
