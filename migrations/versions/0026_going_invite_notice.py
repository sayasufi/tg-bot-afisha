"""inviter-DM dedup ledger for «Я иду»

Revision ID: 0026_going_invite_notice
Revises: 0025_drop_dup_venue_geom_index
Create Date: 2026-06-20

«Я иду» became cancelable (cancel_going hard-deletes the row). Without a durable marker, an invitee
could cancel + re-RSVP to re-fire the inviter DM every time (set_going returns first_time on every
fresh insert). This per-(invitee, event, inviter) ledger gates the DM so the inviter is notified at
most once, surviving any cancel/re-confirm cycle. No FKs (matches event_going.inviter_id) — a log.
"""
from alembic import op

revision = "0026_going_invite_notice"
down_revision = "0025_drop_dup_venue_geom_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS ref.event_going_notice ("
        " telegram_user_id BIGINT NOT NULL,"
        " event_id UUID NOT NULL,"
        " inviter_id BIGINT NOT NULL,"
        " created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
        " PRIMARY KEY (telegram_user_id, event_id, inviter_id))"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ref.event_going_notice")
