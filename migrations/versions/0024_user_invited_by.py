"""user invited_by — referral warm-start (3.4)

Revision ID: 0024_user_invited_by
Revises: 0023_event_going
Create Date: 2026-06-19

The account that first invited a user (a «Пойдём?» share deep-link), set once on the first invite
open — warms a brand-new account's feed from the inviter's taste. Plain BIGINT, no FK.
"""
from alembic import op

revision = "0024_user_invited_by"
down_revision = "0023_event_going"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ref.users ADD COLUMN IF NOT EXISTS invited_by BIGINT")


def downgrade() -> None:
    op.execute("ALTER TABLE ref.users DROP COLUMN IF EXISTS invited_by")
