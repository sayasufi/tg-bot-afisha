"""drop dead ref.users.city_id (city_slug is the single source of truth)

Revision ID: 0018_drop_user_city_id
Revises: 0017_favorites_merged_flag
Create Date: 2026-06-18

city_id was written by /users/location (reverse-geocode → city) but NEVER read by the
app — the Mini App reads city_slug. Two columns, no precedence, was a maintenance hazard.
/location now writes city_slug; drop city_id.
"""
from alembic import op

revision = "0018_drop_user_city_id"
down_revision = "0017_favorites_merged_flag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ref.users DROP COLUMN IF EXISTS city_id")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE ref.users ADD COLUMN IF NOT EXISTS city_id INTEGER "
        "REFERENCES ref.cities(city_id) ON DELETE SET NULL"
    )
