"""telegram_channels.venue_name/venue_address — the known venue for a venue-specific channel

A channel like @dk_crystall or @standupstoremoscow IS one venue, so its posts can carry that venue
authoritatively instead of the LLM re-guessing it from each post (vague «завод на Дубровке») or failing
to place poster-image posts with no address. Stored per channel; passed to extraction as a hint and
used to fill venue/address when the post itself doesn't restate the place.
"""
from alembic import op

revision = "0035_telegram_channel_venue"
down_revision = "0034_raw_processed_hash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ref.telegram_channels ADD COLUMN IF NOT EXISTS venue_name varchar(255)")
    op.execute("ALTER TABLE ref.telegram_channels ADD COLUMN IF NOT EXISTS venue_address varchar(500)")


def downgrade() -> None:
    op.execute("ALTER TABLE ref.telegram_channels DROP COLUMN IF EXISTS venue_address")
    op.execute("ALTER TABLE ref.telegram_channels DROP COLUMN IF EXISTS venue_name")
