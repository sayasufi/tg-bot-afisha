"""raw_events.processed_hash — track the content version that produced the current candidate

Revision ID: 0034_raw_processed_hash
Revises: 0033_digest_default_on
Create Date: 2026-06-22

Raws were normalized exactly once (unprocessed_raw_ids requires candidate_id IS NULL), so when a source
UPDATED a raw (dates shift as old ones pass, a price appears, sessions are added) the candidate + its
occurrences froze at first-ingest. processed_hash stores the content_hash that built the current
candidate; the reprocess-changed flow re-normalizes raws where content_hash <> processed_hash so updates
propagate instead of freezing.
"""
from alembic import op

revision = "0034_raw_processed_hash"
down_revision = "0033_digest_default_on"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE events.raw_events ADD COLUMN IF NOT EXISTS processed_hash varchar(64)")
    # Index the staleness predicate so the reprocess selector (content_hash <> processed_hash) is cheap.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_raw_stale ON events.raw_events (raw_id) "
        "WHERE processed_hash IS NULL OR processed_hash <> content_hash"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS events.ix_raw_stale")
    op.execute("ALTER TABLE events.raw_events DROP COLUMN IF EXISTS processed_hash")
