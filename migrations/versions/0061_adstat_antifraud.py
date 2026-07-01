"""Anti-fraud signals for adstat channel scoring.

Live-verification of the top shortlist exposed manufactured channels (@mosdetail: bought subs 0→380k then
churn, flat ~38k views on every post, ~0% ad conversion) that our point-in-time ERR score ranked «брать».
This adds per-channel anti-fraud signals + a computed multiplier: `af` (raw signals JSONB) and `antifraud`
(the multiplier score applies as final = quality × relevance × coverage × antifraud). NULL antifraud = not
yet scanned → neutral ×1.0.

Revision ID: 0061_adstat_antifraud
Revises: 0060_submission_failed_status
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0061_adstat_antifraud"
down_revision = "0060_submission_failed_status"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("channels", sa.Column("af", postgresql.JSONB(), nullable=True), schema="adstat")
    op.add_column("channels", sa.Column("antifraud", sa.Float(), nullable=True), schema="adstat")
    op.add_column("channels", sa.Column("af_at", sa.DateTime(timezone=True), nullable=True), schema="adstat")


def downgrade():
    op.drop_column("channels", "af_at", schema="adstat")
    op.drop_column("channels", "antifraud", schema="adstat")
    op.drop_column("channels", "af", schema="adstat")
