"""adstat schema — рекламный ресёрч TG-каналов (Telemetr / TGStat / Telethon)

Изолированная схема под скрапер каналов-кандидатов для закупки рекламы.
Не связана с продуктовым пайплайном (ref/events) — отдельная история.

Revision ID: 0038_adstat_schema
Revises: 0037_normalize_moscow_city
Create Date: 2026-06-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0038_adstat_schema"
down_revision = "0037_normalize_moscow_city"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS adstat")

    # Список каналов к скрапингу (что собирать). Заполняется руками/сидом.
    op.create_table(
        "targets",
        sa.Column("target_id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.Text(), nullable=False, unique=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="adstat",
    )

    # Реестр каналов (одна строка на канал; ключ — username, peer_id хранится колонкой).
    op.create_table(
        "channels",
        sa.Column("channel_id", sa.BigInteger(), primary_key=True),
        sa.Column("username", sa.Text(), nullable=False, unique=True),
        sa.Column("peer_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("is_verified", sa.Boolean(), nullable=True),
        sa.Column("ad_price", sa.Integer(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_scraped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="adstat",
    )

    # Снимки статистики — append-only временной ряд (строка на (канал, источник, заход)).
    op.create_table(
        "snapshots",
        sa.Column("snapshot_id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "channel_id", sa.BigInteger(),
            sa.ForeignKey("adstat.channels.channel_id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("source", sa.Text(), nullable=False),  # telemetr | tgstat | telethon
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("subscribers", sa.Integer(), nullable=True),
        sa.Column("er", sa.Float(), nullable=True),               # Telemetr ER, %
        sa.Column("err", sa.Float(), nullable=True),              # TGStat ERR, %
        sa.Column("avg_reach", sa.Integer(), nullable=True),      # средний охват поста
        sa.Column("quality_score", sa.Float(), nullable=True),    # Telemetr оценка качества
        sa.Column("premium_subs", sa.Integer(), nullable=True),
        sa.Column("month_growth", sa.Integer(), nullable=True),   # прирост подписчиков за месяц
        sa.Column("mentions", sa.Integer(), nullable=True),       # TGStat индекс цитирования
        sa.Column("is_scam", sa.Boolean(), nullable=True),
        sa.Column("is_boosting", sa.Boolean(), nullable=True),    # подозрение в накрутке
        sa.Column("is_stolen", sa.Boolean(), nullable=True),
        sa.Column("sanctioned", sa.Boolean(), nullable=True),
        sa.Column("raw", JSONB(), nullable=True),                 # полный сырой ответ источника
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="adstat",
    )
    op.create_index(
        "ix_adstat_snapshots_channel_captured", "snapshots",
        ["channel_id", "captured_at"], schema="adstat",
    )
    op.create_index("ix_adstat_snapshots_source", "snapshots", ["source"], schema="adstat")


def downgrade() -> None:
    op.drop_index("ix_adstat_snapshots_source", table_name="snapshots", schema="adstat")
    op.drop_index("ix_adstat_snapshots_channel_captured", table_name="snapshots", schema="adstat")
    op.drop_table("snapshots", schema="adstat")
    op.drop_table("channels", schema="adstat")
    op.drop_table("targets", schema="adstat")
    op.execute("DROP SCHEMA IF EXISTS adstat CASCADE")
