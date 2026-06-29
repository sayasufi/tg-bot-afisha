"""adstat: средние реакции на пост (сильный сигнал живости — боты не реагируют)

Revision ID: 0049_adstat_reactions
Revises: 0048_adstat_channel_score
Create Date: 2026-06-30
"""
from alembic import op
import sqlalchemy as sa

revision = "0049_adstat_reactions"
down_revision = "0048_adstat_channel_score"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("snapshots", sa.Column("avg_reactions", sa.Integer(), nullable=True), schema="adstat")


def downgrade() -> None:
    op.drop_column("snapshots", "avg_reactions", schema="adstat")
