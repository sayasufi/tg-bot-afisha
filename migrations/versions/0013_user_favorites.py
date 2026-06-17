"""per-user favourites (sync hearts across devices by Telegram account)

Revision ID: 0013_user_favorites
Revises: 0012_search_yo_fold
Create Date: 2026-06-17

Favourites previously lived only in the Mini App's localStorage, so the same Telegram
account saw a different list on each device. Persist them server-side, keyed by the
Telegram user id, so they sync everywhere.
"""
from alembic import op

revision = "0013_user_favorites"
down_revision = "0012_search_yo_fold"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS ref.user_favorites ("
        "  telegram_user_id BIGINT NOT NULL"
        "    REFERENCES ref.users(telegram_user_id) ON DELETE CASCADE,"
        "  event_id UUID NOT NULL,"
        "  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
        "  PRIMARY KEY (telegram_user_id, event_id)"
        ")"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_favorites_user ON ref.user_favorites (telegram_user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ref.user_favorites")
