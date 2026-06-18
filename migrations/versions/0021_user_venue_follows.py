"""venue follows — «следить за площадкой»

Revision ID: 0021_user_venue_follows
Revises: 0020_user_interests
Create Date: 2026-06-18

A user follows a venue; it gives the product a "new at this place" trigger (a later digest)
and a personal venue list. ref.user_venue_follows mirrors ref.user_favorites — a (user, venue)
junction with FK CASCADE on both sides, so a deleted venue/user drops its follows automatically.
"""
from alembic import op

revision = "0021_user_venue_follows"
down_revision = "0020_user_interests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ref.user_venue_follows (
            telegram_user_id BIGINT NOT NULL REFERENCES ref.users(telegram_user_id) ON DELETE CASCADE,
            venue_id INTEGER NOT NULL REFERENCES events.venues(venue_id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (telegram_user_id, venue_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_venue_follows_user ON ref.user_venue_follows (telegram_user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ref.user_venue_follows")
