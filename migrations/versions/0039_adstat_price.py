"""adstat: цена размещения (Telega.in) в снимках

Revision ID: 0039_adstat_price
Revises: 0038_adstat_schema
Create Date: 2026-06-26
"""
from alembic import op
import sqlalchemy as sa


revision = "0039_adstat_price"
down_revision = "0038_adstat_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("snapshots", sa.Column("post_price", sa.Float(), nullable=True), schema="adstat")


def downgrade() -> None:
    op.drop_column("snapshots", "post_price", schema="adstat")
