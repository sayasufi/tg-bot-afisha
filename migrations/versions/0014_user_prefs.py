"""account-scoped app settings (theme, picked city, future prefs)

Revision ID: 0014_user_prefs
Revises: 0013_user_favorites
Create Date: 2026-06-17

Adds ref.users.prefs (JSONB) so Mini App settings sync per Telegram account instead of
living per-device in localStorage. Any future setting is just another key in this blob.
"""
from alembic import op

revision = "0014_user_prefs"
down_revision = "0013_user_favorites"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ref.users ADD COLUMN IF NOT EXISTS prefs JSONB NOT NULL DEFAULT '{}'::jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE ref.users DROP COLUMN IF EXISTS prefs")
