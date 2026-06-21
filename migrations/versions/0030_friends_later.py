"""friends — Later: opt-in @username search + per-account friend-link kill-switch

Revision ID: 0030_friends_later
Revises: 0029_notify_friends
Create Date: 2026-06-21

Two privacy-first refinements. (1) is_searchable: opt-in (default DENY) — only when a user turns it on
can anyone find them by exact @username and send a PENDING friend request (the searcher initiates without
being handed a bearer link, so consent is asymmetric → it goes through the request/accept graph, not
instant). The partial functional index over lower(username) WHERE is_searchable gives an O(log n)
case-insensitive exact match that touches only opt-in rows. (2) friend_link_ver: a per-account version
mixed into the «add me» friend-link HMAC, so a user can rotate (kill) their own outstanding links —
without breaking anyone else's link or any event-invite sig (those share one global secret). ver=0 keeps
the legacy payload, so every link already minted stays valid until its owner resets for the first time.
"""
from alembic import op

revision = "0030_friends_later"
down_revision = "0029_notify_friends"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ref.users ADD COLUMN IF NOT EXISTS is_searchable BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE ref.users ADD COLUMN IF NOT EXISTS friend_link_ver INTEGER NOT NULL DEFAULT 0")
    # Case-insensitive EXACT lookup by handle, over opt-in rows only (smaller + implicitly filters).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_users_username_lower ON ref.users (lower(username)) WHERE is_searchable"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ref.ix_users_username_lower")
    op.execute("ALTER TABLE ref.users DROP COLUMN IF EXISTS friend_link_ver")
    op.execute("ALTER TABLE ref.users DROP COLUMN IF EXISTS is_searchable")
