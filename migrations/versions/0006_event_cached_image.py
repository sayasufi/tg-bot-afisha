"""events.events: add cached_image_url

Holds the URL of our own MinIO-cached, resized copy of the event image
(served via /v1/media); null until the media worker caches it.

Revision ID: 0006_event_cached_image
Revises: 0005_occurrence_unique
Create Date: 2026-06-14
"""

import sqlalchemy as sa
from alembic import op


revision = "0006_event_cached_image"
down_revision = "0005_occurrence_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("cached_image_url", sa.Text(), nullable=True),
        schema="events",
    )


def downgrade() -> None:
    op.drop_column("events", "cached_image_url", schema="events")
