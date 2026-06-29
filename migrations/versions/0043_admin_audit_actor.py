"""admin: аудит-актор как строка (логин), не telegram-id — переход на логин/пароль

Revision ID: 0043_admin_audit_actor
Revises: 0042_admin_panel
Create Date: 2026-06-29
"""
from alembic import op
import sqlalchemy as sa


revision = "0043_admin_audit_actor"
down_revision = "0042_admin_panel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Вход теперь по логину/паролю (один владелец), а не по Telegram — актором аудита стал username.
    op.add_column("admin_audit", sa.Column("actor", sa.Text(), nullable=True), schema="ref")
    op.alter_column("admin_audit", "actor_telegram_id", existing_type=sa.BigInteger(), nullable=True, schema="ref")


def downgrade() -> None:
    op.alter_column("admin_audit", "actor_telegram_id", existing_type=sa.BigInteger(), nullable=False, schema="ref")
    op.drop_column("admin_audit", "actor", schema="ref")
