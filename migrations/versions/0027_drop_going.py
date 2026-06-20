"""drop «Я иду» tables — the RSVP feature was removed (folded into favourites)

Revision ID: 0027_drop_going
Revises: 0026_going_invite_notice
Create Date: 2026-06-21

«Я иду» is gone: accepting a «Пойдём?» invite now just adds the event to favourites, and reminders are
driven by favourites (no per-event bell). The going tables are unused — drop them. Irreversible (RSVP
data is discarded); downgrade recreates the empty tables (mirroring 0023 + 0026) for schema symmetry.
"""
from alembic import op

revision = "0027_drop_going"
down_revision = "0026_going_invite_notice"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ref.event_going_notice")
    op.execute("DROP TABLE IF EXISTS ref.event_going")


def downgrade() -> None:
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
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ref.event_going_notice (
            telegram_user_id BIGINT NOT NULL,
            event_id UUID NOT NULL,
            inviter_id BIGINT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (telegram_user_id, event_id, inviter_id)
        )
        """
    )
