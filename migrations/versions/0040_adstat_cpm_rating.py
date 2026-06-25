"""adstat: CPM + рейтинг канала в снимках

Revision ID: 0040_adstat_cpm_rating
Revises: 0039_adstat_price
Create Date: 2026-06-26
"""
from alembic import op
import sqlalchemy as sa


revision = "0040_adstat_cpm_rating"
down_revision = "0039_adstat_price"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("snapshots", sa.Column("cpm", sa.Float(), nullable=True), schema="adstat")
    op.add_column("snapshots", sa.Column("rating", sa.Float(), nullable=True), schema="adstat")


def downgrade() -> None:
    op.drop_column("snapshots", "rating", schema="adstat")
    op.drop_column("snapshots", "cpm", schema="adstat")
