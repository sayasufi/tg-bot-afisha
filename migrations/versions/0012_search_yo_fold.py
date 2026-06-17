"""search: ё-insensitive functional trigram indexes

The typeahead matches on translate(lower(col), 'ё', 'е') so a query without ё finds a
name WITH ё (and vice-versa) — e.g. "зеленый театр" finds "Зелёный театр ВДНХ". These
expression GIN indexes are on the SAME folded expression the query uses, so the prefix
(LIKE) and fuzzy (%>) branches stay index-driven (no seq scan). The raw trigram indexes
(0001 title, 0011 venue) are left in place — harmless; can be dropped later if unused.
"""
from alembic import op

revision = "0012_search_yo_fold"
down_revision = "0011_search_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_events_title_trgm_e ON events.events "
        "USING gin (translate(lower(canonical_title), 'ё', 'е') gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_venues_name_trgm_e ON events.venues "
        "USING gin (translate(lower(name), 'ё', 'е') gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS events.ix_events_title_trgm_e")
    op.execute("DROP INDEX IF EXISTS events.ix_venues_name_trgm_e")
