"""ref.users: add username + first_name

Revision ID: 0004_user_profile
Revises: 0003_map_places
Create Date: 2026-06-13
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_user_profile"
down_revision = "0003_map_places"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("username", sa.String(64), nullable=True), schema="ref")
    op.add_column("users", sa.Column("first_name", sa.String(128), nullable=True), schema="ref")


def downgrade() -> None:
    op.drop_column("users", "first_name", schema="ref")
    op.drop_column("users", "username", schema="ref")
