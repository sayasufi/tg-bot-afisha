"""ref.users.welcome_nudge_at — идемпотентность одноразового welcome/D1-нуджа.

Юзер, открывший апп но ничего не сохранивший, молчит до пятничного дайджеста (а напоминания требуют
сохранения, которого нет). Через ~1 день после первого открытия шлём 1 персональный DM «события рядом».
Колонка-штамп → каждому ровно один раз.

Revision ID: 0056_user_welcome_nudge
Revises: 0055_adstat_llm_locked
"""
import sqlalchemy as sa
from alembic import op

revision = "0056_user_welcome_nudge"
down_revision = "0055_adstat_llm_locked"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("welcome_nudge_at", sa.DateTime(timezone=True), nullable=True), schema="ref")


def downgrade():
    op.drop_column("users", "welcome_nudge_at", schema="ref")
