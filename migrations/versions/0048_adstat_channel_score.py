"""adstat: наш скор канала на самой строке канала (пересчёт с актуальными подписчиками)

Revision ID: 0048_adstat_channel_score
Revises: 0047_broadcast_local_time
Create Date: 2026-06-30

Раньше админка показывала рейтинг Telega.in (data-raiting) — он не зависит от наших подписчиков. Храним
СВОЙ скор (score.py: качество×релевантность, качество зависит от ERR=охват/подписчики), пересчитанный на
надёжных подписчиках (t.me/telethon), + вердикт «брать/осторожно/мимо». Обновляется flow-ом recompute.
"""
from alembic import op
import sqlalchemy as sa

revision = "0048_adstat_channel_score"
down_revision = "0047_broadcast_local_time"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("channels", sa.Column("score", sa.Integer(), nullable=True), schema="adstat")
    op.add_column("channels", sa.Column("quality", sa.Integer(), nullable=True), schema="adstat")
    op.add_column("channels", sa.Column("verdict", sa.Text(), nullable=True), schema="adstat")
    op.add_column("channels", sa.Column("relevance", sa.Text(), nullable=True), schema="adstat")
    op.add_column("channels", sa.Column("score_at", sa.DateTime(timezone=True), nullable=True), schema="adstat")


def downgrade() -> None:
    for c in ("score_at", "relevance", "verdict", "quality", "score"):
        op.drop_column("channels", c, schema="adstat")
