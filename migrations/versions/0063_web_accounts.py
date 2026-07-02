"""Веб-аккаунты: email+password на ref.users + sequence синтетических id.

Идентичность юзера остаётся telegram_user_id (на нём все таблицы). Веб-регистрация без Telegram
создаёт строку с СИНТЕТИЧЕСКИМ id из ref.web_user_id_seq (старт 10^15 — на порядки выше реальных
TG-id, коллизии невозможны). Связка веб→TG сливает данные синтетической строки в настоящую
TG-строку (и переносит email/password_hash на неё), после чего логин по email ведёт в TG-аккаунт.
Нужна под веб-версию и будущие мобильные приложения (не-Telegram auth).
"""
import sqlalchemy as sa
from alembic import op

revision = "0063_web_accounts"
down_revision = "0062_user_d4_nudge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.Text(), nullable=True), schema="ref")
    op.add_column("users", sa.Column("password_hash", sa.Text(), nullable=True), schema="ref")
    # Уникальность email без регистра; частичный индекс — TG-only юзеры (email NULL) не участвуют.
    op.execute("CREATE UNIQUE INDEX uq_users_email_lower ON ref.users (lower(email)) WHERE email IS NOT NULL")
    op.execute("CREATE SEQUENCE ref.web_user_id_seq START WITH 1000000000000000")


def downgrade() -> None:
    op.execute("DROP SEQUENCE IF EXISTS ref.web_user_id_seq")
    op.execute("DROP INDEX IF EXISTS ref.uq_users_email_lower")
    op.drop_column("users", "password_hash", schema="ref")
    op.drop_column("users", "email", schema="ref")
