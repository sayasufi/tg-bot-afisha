"""закупки рекламы: учёт реальных размещений (канал, цена, время, статус) + привязка к аттрибуции

Revision ID: 0051_ad_buys
Revises: 0050_user_acquisition_source
Create Date: 2026-06-30

Одна строка = одно размещение. src_tag = метка для deep-link (?startapp=src_<tag>) → юзеры с
acq_source=src_tag = «привёл» этой закупки → CPV = цена/привёл. Можно несколько закупок на канал
с разными тегами.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0051_ad_buys"
down_revision = "0050_user_acquisition_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ad_buys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("channel_username", sa.Text(), nullable=False),
        sa.Column("src_tag", sa.Text(), nullable=False),                    # метка аттрибуции (deep-link)
        sa.Column("price", sa.Integer(), nullable=True),                    # ₽
        sa.Column("ad_at", sa.DateTime(timezone=True), nullable=True),      # когда выходит реклама
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'planned'")),  # planned|paid|live|done|cancelled
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="adstat",
    )
    op.create_index("ix_ad_buys_status", "ad_buys", ["status"], schema="adstat")


def downgrade() -> None:
    op.drop_index("ix_ad_buys_status", table_name="ad_buys", schema="adstat")
    op.drop_table("ad_buys", schema="adstat")
