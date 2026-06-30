"""adstat.channels: LLM-категория канала (кэш).

Кейворд-релевантность — вечная игра в whack-a-mole (билеты ПДД ловятся по «билет», «опер»⊂операция и т.п.).
LLM классифицирует канал по названию+username точнее: афиша / город / тема / мусор (+ город). Кэшируем на
канале (llm_category/llm_city/llm_at), recompute предпочитает её, кейворды — дешёвый фолбэк/гейт discovery.

Revision ID: 0054_adstat_llm_category
Revises: 0053_adstat_peer_id_unique
"""
import sqlalchemy as sa
from alembic import op

revision = "0054_adstat_llm_category"
down_revision = "0053_adstat_peer_id_unique"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("channels", sa.Column("llm_category", sa.Text(), nullable=True), schema="adstat")
    op.add_column("channels", sa.Column("llm_city", sa.Text(), nullable=True), schema="adstat")
    op.add_column("channels", sa.Column("llm_at", sa.DateTime(timezone=True), nullable=True), schema="adstat")


def downgrade():
    op.drop_column("channels", "llm_at", schema="adstat")
    op.drop_column("channels", "llm_city", schema="adstat")
    op.drop_column("channels", "llm_category", schema="adstat")
