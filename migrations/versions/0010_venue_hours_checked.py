"""venue hours staleness — auto re-check empty results

Revision ID: 0010_venue_hours_checked
Revises: 0009_event_display_no
Create Date: 2026-06-17

The hours flow only ever resolved venues with hours_json IS NULL, so a venue the
OLD resolver stamped `{}` ("checked, nothing") was never revisited — an improved
resolver couldn't reach it, and transient Yandex failures stuck forever. Add
hours_checked_at so the flow can re-check empty venues on a cadence (self-healing).
Real, non-empty hours are stamped as checked-now so they aren't re-worked; empty
and never-resolved venues stay NULL = due for a (re)check.
"""
from alembic import op

revision = "0010_venue_hours_checked"
down_revision = "0009_event_display_no"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE events.venues ADD COLUMN IF NOT EXISTS hours_checked_at TIMESTAMPTZ")
    op.execute(
        "UPDATE events.venues SET hours_checked_at = now() "
        "WHERE hours_json IS NOT NULL AND hours_json::text <> '{}'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE events.venues DROP COLUMN IF EXISTS hours_checked_at")
