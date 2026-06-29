"""adstat: отметка последней попытки скрапа на таргете (честная ротация дневного scrape)

Revision ID: 0045_adstat_target_scraped
Revises: 0044_source_runs_latest_index
Create Date: 2026-06-29
"""
from alembic import op
import sqlalchemy as sa


revision = "0045_adstat_target_scraped"
down_revision = "0044_source_runs_latest_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Время последней ПОПЫТКИ скрапа (успех ИЛИ ошибка). Дневной scrape берёт срез «самых несвежих»
    # по этому полю — так not_found-таргеты (нет строки в channels) тоже двигаются и не клинят очередь.
    op.add_column(
        "targets",
        sa.Column("last_scraped_at", sa.DateTime(timezone=True), nullable=True),
        schema="adstat",
    )


def downgrade() -> None:
    op.drop_column("targets", "last_scraped_at", schema="adstat")
