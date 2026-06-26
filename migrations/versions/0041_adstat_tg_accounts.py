"""adstat: пул Telethon-аккаунтов

Revision ID: 0041_adstat_tg_accounts
Revises: 0040_adstat_cpm_rating
Create Date: 2026-06-26
"""
from alembic import op
import sqlalchemy as sa


revision = "0041_adstat_tg_accounts"
down_revision = "0040_adstat_cpm_rating"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tg_accounts",
        sa.Column("account_id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.Text(), nullable=False, unique=True),  # телефон/имя
        sa.Column("api_id", sa.BigInteger(), nullable=True),         # null → settings.telethon_api_id
        sa.Column("api_hash", sa.Text(), nullable=True),
        sa.Column("session", sa.Text(), nullable=False),             # Telethon StringSession (секрет)
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("flood_until", sa.DateTime(timezone=True), nullable=True),  # пропускать до этого времени
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="adstat",
    )


def downgrade() -> None:
    op.drop_table("tg_accounts", schema="adstat")
