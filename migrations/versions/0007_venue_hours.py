"""events.venues.hours_json — opening hours (Yandex-resolved, source-agnostic)

Revision ID: 0007_venue_hours
Revises: 0006_event_cached_image
Create Date: 2026-06-15
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_venue_hours"
down_revision = "0006_event_cached_image"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("venues", sa.Column("hours_json", sa.JSON(), nullable=True), schema="events")


def downgrade() -> None:
    op.drop_column("venues", "hours_json", schema="events")
