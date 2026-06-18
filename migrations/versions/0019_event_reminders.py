"""event reminders + notify opt-in columns

Revision ID: 0019_event_reminders
Revises: 0018_drop_user_city_id
Create Date: 2026-06-18

The product's first OUTBOUND channel: a user taps "Напомнить" on a saved event and the
bot DMs them before it starts (a Prefect sweep). ref.event_reminders holds (user, event,
fire_at, sent_at); the partial index serves the due-sweep cheaply. notify_reminders lets a
user globally mute reminders (default on — the per-event tap is the consent); notify_digest
scaffolds the later weekly digest (default off — strictly opt-in).
"""
from alembic import op

revision = "0019_event_reminders"
down_revision = "0018_drop_user_city_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ref.users ADD COLUMN IF NOT EXISTS notify_reminders BOOLEAN NOT NULL DEFAULT true")
    op.execute("ALTER TABLE ref.users ADD COLUMN IF NOT EXISTS notify_digest BOOLEAN NOT NULL DEFAULT false")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ref.event_reminders (
            telegram_user_id BIGINT NOT NULL REFERENCES ref.users(telegram_user_id) ON DELETE CASCADE,
            event_id UUID NOT NULL REFERENCES events.events(event_id) ON DELETE CASCADE,
            fire_at TIMESTAMPTZ NOT NULL,
            sent_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (telegram_user_id, event_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_event_reminders_due "
        "ON ref.event_reminders (fire_at) WHERE sent_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ref.event_reminders")
    op.execute("ALTER TABLE ref.users DROP COLUMN IF EXISTS notify_digest")
    op.execute("ALTER TABLE ref.users DROP COLUMN IF EXISTS notify_reminders")
