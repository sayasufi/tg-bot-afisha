"""ref.users.last_app_open_at — отдельный сигнал ОТКРЫТИЯ мини-приложения.

last_active_at бьётся ботом на любой /start, /help, /digest — поэтому «удержан/активен» в воронке закупок
завышались бот-командами (юзер ни разу не открыл апп, но тапнул /start в ответ на DM → засчитан). Новая
колонка бампается ТОЛЬКО в app-роутах (bootstrap) → retained/active7 считаем по ней. Для прошлых юзеров
NULL (честно: открытий апп до этого не трекали) — заполнится по мере заходов.

Revision ID: 0052_user_last_app_open
Revises: 0051_ad_buys
"""
import sqlalchemy as sa
from alembic import op

revision = "0052_user_last_app_open"
down_revision = "0051_ad_buys"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("last_app_open_at", sa.DateTime(timezone=True), nullable=True), schema="ref")
    op.create_index("ix_users_last_app_open_at", "users", ["last_app_open_at"], schema="ref")


def downgrade():
    op.drop_index("ix_users_last_app_open_at", table_name="users", schema="ref")
    op.drop_column("users", "last_app_open_at", schema="ref")
