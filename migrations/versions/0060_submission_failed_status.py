"""Add a 'failed' status to ref.pending_submissions.

The status-watch flow flips an APPROVED submission that never materialized (event not recognized /
address ungeocodable / channel unreadable) to 'failed' + an honest DM — so nothing hangs in 'approved'
and the admin gets a «не удалось» view.

Revision ID: 0060_submission_failed_status
Revises: 0059_pending_submissions
"""
from alembic import op

revision = "0060_submission_failed_status"
down_revision = "0059_pending_submissions"
branch_labels = None
depends_on = None

_WITH = "('pending','auto_rejected','needs_review','approved','rejected','ingested','failed')"
_WITHOUT = "('pending','auto_rejected','needs_review','approved','rejected','ingested')"


def upgrade():
    op.execute("ALTER TABLE ref.pending_submissions DROP CONSTRAINT ck_pending_status")
    op.execute(f"ALTER TABLE ref.pending_submissions ADD CONSTRAINT ck_pending_status CHECK (status IN {_WITH})")


def downgrade():
    op.execute("ALTER TABLE ref.pending_submissions DROP CONSTRAINT ck_pending_status")
    op.execute(f"ALTER TABLE ref.pending_submissions ADD CONSTRAINT ck_pending_status CHECK (status IN {_WITHOUT})")
