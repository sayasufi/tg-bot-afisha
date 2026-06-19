"""digest perf — idempotency ledger + sweep indexes

Revision ID: 0022_digest_perf
Revises: 0021_user_venue_follows
Create Date: 2026-06-19

The weekly digest gains a per-send ledger (ref.users.last_digest_sent_at) so a redeploy/manual
re-run/missed-run catchup in the same week can't double-send. Plus three indexes the sweep leans
on: events.created_at (the "new this week" filter), and (event_id, date_start) / (venue_id,
date_start) on event_occurrences (the future-first DISTINCT ON + followed-venue lookups).
No CONCURRENTLY — this runs inside the migration txn; the affected tables are small.
"""
from alembic import op

revision = "0022_digest_perf"
down_revision = "0021_user_venue_follows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ref.users ADD COLUMN IF NOT EXISTS last_digest_sent_at TIMESTAMPTZ")
    op.execute("CREATE INDEX IF NOT EXISTS ix_events_created_at ON events.events (created_at)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_occurrences_event_date ON events.event_occurrences (event_id, date_start)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_occurrences_venue_date ON events.event_occurrences (venue_id, date_start)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS events.ix_occurrences_venue_date")
    op.execute("DROP INDEX IF EXISTS events.ix_occurrences_event_date")
    op.execute("DROP INDEX IF EXISTS events.ix_events_created_at")
    op.execute("ALTER TABLE ref.users DROP COLUMN IF EXISTS last_digest_sent_at")
