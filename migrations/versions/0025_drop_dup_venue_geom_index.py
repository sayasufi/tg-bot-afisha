"""drop the duplicate venues gist index (write-overhead cleanup)

Revision ID: 0025_drop_dup_venue_geom_index
Revises: 0024_user_invited_by
Create Date: 2026-06-20

GeoAlchemy auto-creates idx_venues_geom (spatial_index defaults to True on a Geography column) ON TOP
OF the explicit ix_venues_geom the model + migration 0001 declare — two identical gist(geom) indexes.
EXPLAIN ANALYZE at current scale (~1.2k venues, fully cached) shows the planner seq-scans venues
regardless, so the duplicate buys nothing and just doubles the gist write/maintenance cost on every
venue upsert. Keep ix_venues_geom, drop the auto one. The model now sets spatial_index=False so a fresh
DB never recreates it. Deliberately NO new indexes added: at this scale the planner prefers seq scans
on these small in-memory tables, so a speculative index would be dead weight (and slow writes).
"""
from alembic import op

revision = "0025_drop_dup_venue_geom_index"
down_revision = "0024_user_invited_by"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS events.idx_venues_geom")


def downgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS idx_venues_geom ON events.venues USING gist (geom)")
