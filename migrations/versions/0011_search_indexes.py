"""search indexes — venue-name trigram for the typeahead search

The multi-field search matches venue names (find events at "Большой театр") via
ILIKE/word_similarity, so venues.name needs a pg_trgm GIN index or it seq-scans.
The event-title trigram (ix_events_title_trgm, migration 0001) and the display_no
unique index (migration 0009, for the code fast-path) are reused as-is.

Tiny tables (~1.2k venues) → a plain CREATE INDEX locks for ms; no CONCURRENTLY
needed (and CONCURRENTLY can't run inside the alembic migration transaction).
"""
from alembic import op

revision = "0011_search_indexes"
down_revision = "0010_venue_hours_checked"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_venues_name_trgm ON events.venues USING gin (name gin_trgm_ops)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS events.ix_venues_name_trgm")
