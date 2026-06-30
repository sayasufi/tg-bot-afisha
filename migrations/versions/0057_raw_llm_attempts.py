"""events.raw_events.llm_attempts — счётчик попыток для retry транзиентных LLM-skip.

Транзиентный сбой LLM ставит skip_reason='llm_error'/'invalid_json', а unprocessed_raw_ids переоткрывает
строку только при смене content_hash → тот же TG-пост НИКОГДА не переобрабатывается (дыры в единственном
first-party-источнике). Флоу retry-transient-skips переоткрывает такие строки, инкрементя счётчик, и помечает
'llm_error_dead' после N попыток — чтобы битая строка не крутилась вечно.

Revision ID: 0057_raw_llm_attempts
Revises: 0056_user_welcome_nudge
"""
import sqlalchemy as sa
from alembic import op

revision = "0057_raw_llm_attempts"
down_revision = "0056_user_welcome_nudge"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("raw_events", sa.Column("llm_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")), schema="events")


def downgrade():
    op.drop_column("raw_events", "llm_attempts", schema="events")
