"""telegram_channels.subscribers — cached subscriber count per channel

Stored so we can rank/filter channels by reach and see the smallest ones at a glance. Refreshed by
the daily refresh-channel-subscribers flow (parses the t.me/<channel> page). Nullable until first fetch.
"""
from alembic import op

revision = "0036_telegram_channel_subscribers"
down_revision = "0035_telegram_channel_venue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ref.telegram_channels ADD COLUMN IF NOT EXISTS subscribers integer")


def downgrade() -> None:
    op.execute("ALTER TABLE ref.telegram_channels DROP COLUMN IF EXISTS subscribers")
