"""replace user prefs JSONB with explicit setting columns

Revision ID: 0015_user_settings_columns
Revises: 0014_user_prefs
Create Date: 2026-06-18

Settings as a JSONB blob was a mistake — make them proper typed columns: theme, picked
city, and the first-run flags (onboarded / coach / swipe hint), all account-scoped.
"""
from alembic import op

revision = "0015_user_settings_columns"
down_revision = "0014_user_prefs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ref.users ADD COLUMN IF NOT EXISTS theme VARCHAR(8)")
    op.execute("ALTER TABLE ref.users ADD COLUMN IF NOT EXISTS city_slug VARCHAR(64)")
    op.execute("ALTER TABLE ref.users ADD COLUMN IF NOT EXISTS onboarded BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE ref.users ADD COLUMN IF NOT EXISTS coach BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE ref.users ADD COLUMN IF NOT EXISTS swipe_seen BOOLEAN NOT NULL DEFAULT false")
    # Carry over anything already written into the short-lived prefs blob, then drop it.
    op.execute("UPDATE ref.users SET theme = prefs->>'theme' WHERE prefs ? 'theme' AND theme IS NULL")
    op.execute("UPDATE ref.users SET city_slug = prefs->>'city' WHERE prefs ? 'city' AND city_slug IS NULL")
    op.execute("ALTER TABLE ref.users DROP COLUMN IF EXISTS prefs")


def downgrade() -> None:
    op.execute("ALTER TABLE ref.users ADD COLUMN IF NOT EXISTS prefs JSONB NOT NULL DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE ref.users DROP COLUMN IF EXISTS theme")
    op.execute("ALTER TABLE ref.users DROP COLUMN IF EXISTS city_slug")
    op.execute("ALTER TABLE ref.users DROP COLUMN IF EXISTS onboarded")
    op.execute("ALTER TABLE ref.users DROP COLUMN IF EXISTS coach")
    op.execute("ALTER TABLE ref.users DROP COLUMN IF EXISTS swipe_seen")
