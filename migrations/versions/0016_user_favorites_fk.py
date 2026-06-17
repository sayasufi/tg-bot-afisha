"""favourites: FK to events with ON DELETE CASCADE (no more dangling rows)

Revision ID: 0016_user_favorites_fk
Revises: 0015_user_settings_columns
Create Date: 2026-06-18

Replaces the "no FK + prune on every sync" approach: a real FK with ON DELETE CASCADE
means a favourite is removed exactly when its event is (by the dedup/lifecycle pipeline),
so there are never dangling rows inflating the count — and we stop deleting favourites of
events that have merely passed (that erased the user's history). Pre-clean existing
orphans so the constraint validates.
"""
from alembic import op

revision = "0016_user_favorites_fk"
down_revision = "0015_user_settings_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop favourites whose event no longer exists, so ADD CONSTRAINT ... VALIDATE passes.
    op.execute(
        "DELETE FROM ref.user_favorites uf "
        "WHERE NOT EXISTS (SELECT 1 FROM events.events e WHERE e.event_id = uf.event_id)"
    )
    # NOT VALID + VALIDATE avoids a long ACCESS EXCLUSIVE lock on a populated table.
    op.execute(
        "ALTER TABLE ref.user_favorites ADD CONSTRAINT user_favorites_event_fk "
        "FOREIGN KEY (event_id) REFERENCES events.events(event_id) ON DELETE CASCADE NOT VALID"
    )
    op.execute("ALTER TABLE ref.user_favorites VALIDATE CONSTRAINT user_favorites_event_fk")


def downgrade() -> None:
    op.execute("ALTER TABLE ref.user_favorites DROP CONSTRAINT IF EXISTS user_favorites_event_fk")
