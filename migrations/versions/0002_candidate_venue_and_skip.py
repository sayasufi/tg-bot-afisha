"""event_candidates.venue_id + raw_events.skip_reason

Revision ID: 0002_candidate_venue_and_skip
Revises: 0001_init
Create Date: 2026-06-13
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_candidate_venue_and_skip"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "event_candidates",
        sa.Column("venue_id", sa.Integer(), nullable=True),
        schema="events",
    )
    op.create_foreign_key(
        "fk_event_candidates_venue_id",
        "event_candidates",
        "venues",
        ["venue_id"],
        ["venue_id"],
        source_schema="events",
        referent_schema="events",
        ondelete="SET NULL",
    )
    op.add_column(
        "raw_events",
        sa.Column("skip_reason", sa.String(64), nullable=False, server_default=""),
        schema="events",
    )


def downgrade() -> None:
    op.drop_column("raw_events", "skip_reason", schema="events")
    op.drop_constraint("fk_event_candidates_venue_id", "event_candidates", schema="events", type_="foreignkey")
    op.drop_column("event_candidates", "venue_id", schema="events")
