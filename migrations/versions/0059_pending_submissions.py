"""ref.pending_submissions — user-submitted events (and, later, channels) awaiting admin moderation.

A durable queue for «предложить своё мероприятие / добавить свой канал». One row per submission: a kind,
a status state-machine, the submitted data (JSONB), cheap auto-validation signals (JSONB), and the
moderation outcome. Approved EVENTS flow into the pipeline via events.raw_events under a per-city
`user_submission-<slug>` source (so geocoding/dedup/category run as usual); approved CHANNELS (Ф2) into
ref.telegram_channels. Kept OUT of events/telegram_channels until approved (those tables have no 'pending'
state — Event.status is only active/hidden).

Revision ID: 0059_pending_submissions
Revises: 0058_raw_unprocessed_index
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0059_pending_submissions"
down_revision = "0058_raw_unprocessed_index"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pending_submissions",
        sa.Column("submission_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="needs_review"),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("checks", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("submitted_by", sa.BigInteger(), nullable=False),
        sa.Column("submitted_username", sa.Text(), nullable=True),
        sa.Column("city_slug", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reject_code", sa.Text(), nullable=True),
        sa.Column("target_raw_id", sa.Integer(), nullable=True),
        sa.Column("target_channel_id", sa.Integer(), nullable=True),
        sa.Column("target_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("kind IN ('event','channel')", name="ck_pending_kind"),
        sa.CheckConstraint(
            "status IN ('pending','auto_rejected','needs_review','approved','rejected','ingested')",
            name="ck_pending_status",
        ),
        schema="ref",
    )
    # Queue read paths: newest-first per status, and per-user (for the daily submit cap fallback).
    op.execute("CREATE INDEX ix_pending_status_created ON ref.pending_submissions (status, created_at DESC)")
    op.execute("CREATE INDEX ix_pending_by_user ON ref.pending_submissions (submitted_by, created_at DESC)")
    # Anti-abuse: forbid two OPEN channel submissions of the same (normalized) username. NULL for events
    # (username_norm absent) never conflicts, so this is a no-op for the event kind.
    op.execute(
        "CREATE UNIQUE INDEX uq_pending_channel_open ON ref.pending_submissions ((data->>'username_norm')) "
        "WHERE kind = 'channel' AND status IN ('pending', 'needs_review')"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ref.uq_pending_channel_open")
    op.execute("DROP INDEX IF EXISTS ref.ix_pending_by_user")
    op.execute("DROP INDEX IF EXISTS ref.ix_pending_status_created")
    op.drop_table("pending_submissions", schema="ref")
