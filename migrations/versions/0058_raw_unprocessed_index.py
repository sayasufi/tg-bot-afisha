"""Partial index for the hot unprocessed-raw selector (the normalize queue).

unprocessed_raw_ids runs every 60s (up to 8×/normalize run): SELECT raw_id FROM events.raw_events LEFT JOIN
event_candidates ... WHERE candidate_id IS NULL AND skip_reason = '' ORDER BY raw_id LIMIT 100. raw_events
grows monotonically (no DELETEs anywhere), so without an index matching the predicate Postgres walks an
ever-larger PK rechecking skip_reason on every probe — a hot query that degrades as the biggest table grows.
This PARTIAL index covers only the OPEN rows (skip_reason = ''): it's tiny, gives an index-scan already
ordered by raw_id (no sort), and shrinks automatically as rows get a skip_reason / a candidate.

Built CONCURRENTLY (outside the migration transaction) so it never write-locks the large raw_events table.

Revision ID: 0058_raw_unprocessed_index
Revises: 0057_raw_llm_attempts
"""
from alembic import op

revision = "0058_raw_unprocessed_index"
down_revision = "0057_raw_llm_attempts"
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_raw_unprocessed "
            "ON events.raw_events (raw_id) WHERE skip_reason = ''"
        )


def downgrade():
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS events.ix_raw_unprocessed")
