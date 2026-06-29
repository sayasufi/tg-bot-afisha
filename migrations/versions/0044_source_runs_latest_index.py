"""perf: индекс для «последний прогон по источнику» (admin ingest-health, 376 источников)

Revision ID: 0044_source_runs_latest_index
Revises: 0043_admin_audit_actor
Create Date: 2026-06-29
"""
from alembic import op
import sqlalchemy as sa


revision = "0044_source_runs_latest_index"
down_revision = "0043_admin_audit_actor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # LATERAL «последний run по source_id» (admin /overview + /health) без этого индекса = 376 сканов
    # source_runs (~15с). С (source_id, started_at DESC) — индекс-проба + LIMIT 1 на источник → миллисекунды.
    op.create_index(
        "ix_source_runs_source_started",
        "source_runs",
        ["source_id", sa.text("started_at DESC")],
        schema="events",
    )


def downgrade() -> None:
    op.drop_index("ix_source_runs_source_started", table_name="source_runs", schema="events")
