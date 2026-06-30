"""adstat.channels: partial UNIQUE на peer_id — один TG-канал = одна строка даже при смене @username.

persist_snapshots теперь ищет канал по peer_id и обновляет ту же строку при ренейме (а не вставляет дубль).
Индекс закрепляет инвариант. Частичный (WHERE peer_id IS NOT NULL): у части каналов peer_id неизвестен.
На момент миграции дублей по peer_id 0 — создаётся безопасно.

Revision ID: 0053_adstat_peer_id_unique
Revises: 0052_user_last_app_open
"""
import sqlalchemy as sa
from alembic import op

revision = "0053_adstat_peer_id_unique"
down_revision = "0052_user_last_app_open"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "uq_channels_peer_id", "channels", ["peer_id"], unique=True, schema="adstat",
        postgresql_where=sa.text("peer_id IS NOT NULL"),
    )


def downgrade():
    op.drop_index("uq_channels_peer_id", table_name="channels", schema="adstat")
