"""favorites_merged flag — stop stale devices resurrecting removed favourites

Revision ID: 0017_favorites_merged_flag
Revises: 0016_user_favorites_fk
Create Date: 2026-06-18

The one-time localStorage->account merge is a pure union with no tombstones, so a device
that never synced could re-add (on its first sync) a favourite the user removed on another
device. Gate the merge on this flag: once an account has merged, ignore further `add`
lists. Backfill true for any account that already has favourites (migration complete).
"""
from alembic import op

revision = "0017_favorites_merged_flag"
down_revision = "0016_user_favorites_fk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ref.users ADD COLUMN IF NOT EXISTS favorites_merged BOOLEAN NOT NULL DEFAULT false")
    op.execute(
        "UPDATE ref.users u SET favorites_merged = true "
        "WHERE EXISTS (SELECT 1 FROM ref.user_favorites f WHERE f.telegram_user_id = u.telegram_user_id)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE ref.users DROP COLUMN IF EXISTS favorites_merged")
