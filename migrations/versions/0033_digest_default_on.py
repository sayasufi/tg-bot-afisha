"""digest opt-OUT: notify_digest default true + flip existing users on

Revision ID: 0033_digest_default_on
Revises: 0032_user_favorites_created_idx
Create Date: 2026-06-22

The weekly «Афиша на выходные» digest is the main re-engagement loop, but as an opt-in (default false) it
reached almost nobody (2/7). Flip it to opt-OUT: default true for new users + flip existing users on — they
never opted OUT, the feature was just off by default. The «quiet if nothing fresh» guard already prevents
empty sends, and Profile → «Афиша на выходные» (or /digest in the bot) is the opt-out.
"""
from alembic import op

revision = "0033_digest_default_on"
down_revision = "0032_user_favorites_created_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ref.users ALTER COLUMN notify_digest SET DEFAULT true")
    op.execute("UPDATE ref.users SET notify_digest = true WHERE notify_digest = false")


def downgrade() -> None:
    op.execute("ALTER TABLE ref.users ALTER COLUMN notify_digest SET DEFAULT false")
