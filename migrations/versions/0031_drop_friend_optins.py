"""drop the friend opt-in columns — @username search + friend DMs are now ALWAYS ON

Revision ID: 0031_drop_friend_optins
Revises: 0030_friends_later
Create Date: 2026-06-22

The «Находить меня по @username» (is_searchable) and «О друзьях» (notify_friends) toggles were removed —
everyone is findable by exact handle and everyone always gets friend notifications — so both columns are
dead. Drop them so they don't linger. The old username index was PARTIAL (WHERE is_searchable), which the
now-unfiltered lookup can't use, so swap it for a full lower(username) index that keeps the exact-handle
match O(log n). friend_link_ver (single-use link) and friends_private (the kept «скрыть от друзей» toggle)
stay. Reversible: downgrade re-adds the columns at their old defaults and restores the partial index.
"""
from alembic import op

revision = "0031_drop_friend_optins"
down_revision = "0030_friends_later"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # find_searchable no longer filters on is_searchable, so its partial index is dead — replace it with a
    # full lower(username) index covering the now-everyone exact-handle lookup before dropping the column.
    op.execute("DROP INDEX IF EXISTS ref.ix_users_username_lower")
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_username_lower ON ref.users (lower(username))")
    op.execute("ALTER TABLE ref.users DROP COLUMN IF EXISTS is_searchable")
    op.execute("ALTER TABLE ref.users DROP COLUMN IF EXISTS notify_friends")


def downgrade() -> None:
    op.execute("ALTER TABLE ref.users ADD COLUMN IF NOT EXISTS notify_friends BOOLEAN NOT NULL DEFAULT true")
    op.execute("ALTER TABLE ref.users ADD COLUMN IF NOT EXISTS is_searchable BOOLEAN NOT NULL DEFAULT false")
    op.execute("DROP INDEX IF EXISTS ref.ix_users_username_lower")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_users_username_lower ON ref.users (lower(username)) WHERE is_searchable"
    )
