"""notify_friends opt-in — gates friend DMs + the «что сохранили друзья» digest section

Revision ID: 0029_notify_friends
Revises: 0028_friends
Create Date: 2026-06-21

A dedicated friend-notification toggle, separate from notify_reminders (event reminders) and
notify_digest (the weekly roundup itself). Default TRUE — friend notifications are on, mutable — so the
«X добавил тебя в друзья» DM and the digest's friends section show unless the user turns them off.
"""
from alembic import op

revision = "0029_notify_friends"
down_revision = "0028_friends"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ref.users ADD COLUMN IF NOT EXISTS notify_friends BOOLEAN NOT NULL DEFAULT true")


def downgrade() -> None:
    op.execute("ALTER TABLE ref.users DROP COLUMN IF EXISTS notify_friends")
