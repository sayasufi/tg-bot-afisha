"""attribution: источник привлечения юзера (first-touch) — какой рекл. канал/кампания привёл

Revision ID: 0050_user_acquisition_source
Revises: 0049_adstat_reactions
Create Date: 2026-06-30

Ставится ОДИН раз при первом открытии по deep-link `?startapp=src_<channel>` (или /start src_<...>).
acq_source = то, что после `src_` (обычно username канала) → джойн к adstat.channels.username даёт
конверсии по каналу. Не перезаписывается (первое касание).
"""
from alembic import op
import sqlalchemy as sa

revision = "0050_user_acquisition_source"
down_revision = "0049_adstat_reactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("acq_source", sa.Text(), nullable=True), schema="ref")
    op.add_column("users", sa.Column("acq_at", sa.DateTime(timezone=True), nullable=True), schema="ref")
    op.create_index("ix_users_acq_source", "users", ["acq_source"], schema="ref")


def downgrade() -> None:
    op.drop_index("ix_users_acq_source", table_name="users", schema="ref")
    op.drop_column("users", "acq_at", schema="ref")
    op.drop_column("users", "acq_source", schema="ref")
