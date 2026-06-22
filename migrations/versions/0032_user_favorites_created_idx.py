"""index user_favorites (telegram_user_id, created_at desc) — for the «Хроника друзей» feed sort

Revision ID: 0032_user_favorites_created_idx
Revises: 0031_drop_friend_optins
Create Date: 2026-06-22

friend_activity() orders my friends' favourites by created_at DESC and takes the newest few. With only the
(telegram_user_id) index, Postgres read every favourite of every friend and top-N sorted them on each
(uncached) «Друзья» open. A composite (telegram_user_id, created_at DESC) index serves the per-friend
newest-first scan directly. Small table, instant build.
"""
from alembic import op

revision = "0032_user_favorites_created_idx"
down_revision = "0031_drop_friend_optins"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_favorites_user_created "
        "ON ref.user_favorites (telegram_user_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ref.ix_user_favorites_user_created")
