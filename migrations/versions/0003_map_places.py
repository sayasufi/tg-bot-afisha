"""ref.map_places — curated map overlay points (metro, parks, …)

Revision ID: 0003_map_places
Revises: 0002_candidate_venue_and_skip
Create Date: 2026-06-13
"""

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geography


revision = "0003_map_places"
down_revision = "0002_candidate_venue_and_skip"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "map_places",
        sa.Column("place_id", sa.Integer(), primary_key=True),
        sa.Column("city_id", sa.Integer(), sa.ForeignKey("ref.cities.city_id", ondelete="SET NULL"), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("geom", Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False),
        sa.Column("color", sa.String(16), nullable=True),
        sa.Column("source", sa.String(64), nullable=False, server_default=""),
        sa.Column("meta_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("kind", "city_id", "name", name="uq_map_place_kind_city_name"),
        schema="ref",
    )
    op.create_index("ix_map_places_kind_city", "map_places", ["kind", "city_id"], schema="ref")
    op.create_index("ix_map_places_geom", "map_places", ["geom"], schema="ref", postgresql_using="gist")


def downgrade() -> None:
    op.drop_index("ix_map_places_geom", table_name="map_places", schema="ref")
    op.drop_index("ix_map_places_kind_city", table_name="map_places", schema="ref")
    op.drop_table("map_places", schema="ref")
