"""ref.users.d4_nudge_at — идемпотентность одноразового D4-D5 нуджа не-сохранившим.

Закрывает «мёртвую зону» D2-D6 (после welcome/D1 и до пятничного дайджеста — ноль касаний).
Жёсткий кап: welcome (D1) + этот (D4-5) = максимум два нуджа не-сохранившему, дальше только
opt-in дайджест. NULL = не отправлялся.
"""
import sqlalchemy as sa
from alembic import op

revision = "0062_user_d4_nudge"
down_revision = "0061_adstat_antifraud"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("d4_nudge_at", sa.DateTime(timezone=True), nullable=True), schema="ref")


def downgrade() -> None:
    op.drop_column("users", "d4_nudge_at", schema="ref")
