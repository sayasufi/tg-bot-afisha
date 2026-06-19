"""event going — «Я иду» / the «Пойдём?» social loop

Revision ID: 0023_event_going
Revises: 0022_digest_perf
Create Date: 2026-06-19

A user accepts a shared invite («Я иду») — ref.event_going is a (user, event) junction with the
inviter who shared it, FK CASCADE on both sides. Powers the answerable-invite DM to the inviter
and a future «N собираются» count (hence the event_id index).
"""
from alembic import op

revision = "0023_event_going"
down_revision = "0022_digest_perf"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ref.event_going (
            telegram_user_id BIGINT NOT NULL REFERENCES ref.users(telegram_user_id) ON DELETE CASCADE,
            event_id UUID NOT NULL REFERENCES events.events(event_id) ON DELETE CASCADE,
            inviter_id BIGINT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (telegram_user_id, event_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_event_going_event ON ref.event_going (event_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ref.event_going")
