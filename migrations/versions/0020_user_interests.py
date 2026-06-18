"""user interest picker (cold-start) — categories chosen at first-run onboarding

Revision ID: 0020_user_interests
Revises: 0019_event_reminders
Create Date: 2026-06-18

A brand-new account has no affinity (no favourites, no opens), so its "Для тебя" feed was
popularity-only yet labelled as personal. The first-run onboarding now asks the user to tap
3+ categories; we store those slugs here so the feed is warm — genuinely personal — from the
very first open. A small text[] on ref.users, alongside the other typed app settings.
"""
from alembic import op

revision = "0020_user_interests"
down_revision = "0019_event_reminders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ref.users ADD COLUMN IF NOT EXISTS interests TEXT[] NOT NULL DEFAULT '{}'")


def downgrade() -> None:
    op.execute("ALTER TABLE ref.users DROP COLUMN IF EXISTS interests")
