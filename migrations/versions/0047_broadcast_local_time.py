"""broadcast at_local: целевой локальный час/дата (отправка «в HH:00 по времени города»)

Revision ID: 0047_broadcast_local_time
Revises: 0046_broadcast_campaigns
Create Date: 2026-06-29

local_hour (0..23) + local_date — цель в ЛОКАЛЬНОЙ таймзоне каждого получателя. Диспетчер каждый тик
шлёт подаудитории, у кого now()+offset(city) уже достиг (local_date+local_hour); ledger = идемпотентность,
итерации по городам НЕТ (это давало дабл-сенд/потерю null-city). Юзеры без города → офсет +3.
"""
from alembic import op
import sqlalchemy as sa

revision = "0047_broadcast_local_time"
down_revision = "0046_broadcast_campaigns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("broadcast_campaigns", sa.Column("local_hour", sa.Integer(), nullable=True), schema="ref")
    op.add_column("broadcast_campaigns", sa.Column("local_date", sa.Date(), nullable=True), schema="ref")


def downgrade() -> None:
    op.drop_column("broadcast_campaigns", "local_date", schema="ref")
    op.drop_column("broadcast_campaigns", "local_hour", schema="ref")
