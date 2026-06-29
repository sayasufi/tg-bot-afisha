"""admin panel: live-настройки (app_settings) + аудит действий + версия admin-сессии

Revision ID: 0042_admin_panel
Revises: 0041_adstat_tg_accounts
Create Date: 2026-06-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0042_admin_panel"
down_revision = "0041_adstat_tg_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ref.app_settings — live override-слой поверх замороженного lru_cache-конфига. key→JSONB.
    # Точки чтения берут get_effective(key) = override ?? get_settings().field (Redis-кэш TTL~30с),
    # чтобы тогл/порог подействовал near-live без рестарта во всех процессах.
    op.create_table(
        "app_settings",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),  # telegram_user_id
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="ref",
    )

    # ref.admin_audit — журнал ВСЕХ админ-действий (вход/выход, запуск флоу, мёрджи, рассылки, правка
    # настроек). params без значений секретов.
    op.create_table(
        "admin_audit",
        sa.Column("audit_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("actor_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target", sa.Text(), nullable=True),
        sa.Column("params", postgresql.JSONB(), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("ip", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="ref",
    )
    op.create_index("ix_admin_audit_created", "admin_audit", [sa.text("created_at DESC")], schema="ref")
    op.create_index("ix_admin_audit_actor", "admin_audit", ["actor_telegram_id"], schema="ref")

    # Версия admin-сессии (паттерн friend_link_ver) — бамп = мгновенный отзыв всех токенов владельца.
    op.add_column(
        "users",
        sa.Column("admin_session_ver", sa.Integer(), nullable=False, server_default=sa.text("0")),
        schema="ref",
    )


def downgrade() -> None:
    op.drop_column("users", "admin_session_ver", schema="ref")
    op.drop_index("ix_admin_audit_actor", table_name="admin_audit", schema="ref")
    op.drop_index("ix_admin_audit_created", table_name="admin_audit", schema="ref")
    op.drop_table("admin_audit", schema="ref")
    op.drop_table("app_settings", schema="ref")
