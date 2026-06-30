"""adstat.channels.llm_locked — категория, выставленная ОПЕРАТОРОМ вручную (не перезаписывается авто-LLM).

LLM-классификация по названию+username точна, но не 100% (напр. «Радар Москва» — неоднозначно). Оператор
правит категорию одним кликом; llm_locked=true → classify_channels_llm пропускает канал, recompute уважает
ручную категорию. Закрывает остаток, который автоклассификатор не берёт.

Revision ID: 0055_adstat_llm_locked
Revises: 0054_adstat_llm_category
"""
import sqlalchemy as sa
from alembic import op

revision = "0055_adstat_llm_locked"
down_revision = "0054_adstat_llm_category"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("channels", sa.Column("llm_locked", sa.Boolean(), nullable=False, server_default=sa.text("false")), schema="adstat")


def downgrade():
    op.drop_column("channels", "llm_locked", schema="adstat")
