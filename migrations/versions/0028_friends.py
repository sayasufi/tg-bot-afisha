"""friends graph — Phase 1 (mutual edge born from an accepted «Пойдём?» invite)

Revision ID: 0028_friends
Revises: 0027_drop_going
Create Date: 2026-06-21

The friend graph is a SYMMETRIC two-row edge (ref.user_friends): accepting a signed «Пойдём?» invite
makes the inviter and invitee mutual friends, so the hot query «which of my friends favorited these
events» is one index JOIN on (user_id) with no OR/LEAST. ref.user_mutes carries block/mute. Two privacy
columns ship WITH the named signal so the first release can't out anyone retroactively: a global
friends_private kill-switch and a per-favourite hidden_from_friends. photo_url stores the friend's TG
avatar (captured from initData) for the social-proof faces. The missing ix on user_favorites(event_id)
backs the reverse JOIN. Graph is back-filled from already-accepted invites (ref.users.invited_by).
"""
from alembic import op

revision = "0028_friends"
down_revision = "0027_drop_going"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Symmetric friendship edge. src_event_id is plain UUID (informational attribution, like
    # users.invited_by) — no FK, so deleting the source event never drops the friendship.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ref.user_friends (
            user_id     BIGINT NOT NULL REFERENCES ref.users(telegram_user_id) ON DELETE CASCADE,
            friend_id   BIGINT NOT NULL REFERENCES ref.users(telegram_user_id) ON DELETE CASCADE,
            status      TEXT NOT NULL DEFAULT 'accepted' CHECK (status IN ('pending', 'accepted')),
            src_event_id UUID,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, friend_id),
            CHECK (user_id <> friend_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ref.user_mutes (
            user_id        BIGINT NOT NULL REFERENCES ref.users(telegram_user_id) ON DELETE CASCADE,
            muted_user_id  BIGINT NOT NULL REFERENCES ref.users(telegram_user_id) ON DELETE CASCADE,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, muted_user_id),
            CHECK (user_id <> muted_user_id)
        )
        """
    )
    # Reverse JOIN «who favorited event X» — the PK on user_favorites leads with telegram_user_id,
    # so a lookup by event_id alone was a seq-scan (deadly under pool_size=5 once friends-favorited runs).
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_favorites_event ON ref.user_favorites (event_id)")
    # Privacy + identity columns (NOT NULL DEFAULT false → safe for existing rows).
    op.execute("ALTER TABLE ref.users ADD COLUMN IF NOT EXISTS friends_private BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE ref.users ADD COLUMN IF NOT EXISTS photo_url TEXT")
    op.execute("ALTER TABLE ref.user_favorites ADD COLUMN IF NOT EXISTS hidden_from_friends BOOLEAN NOT NULL DEFAULT false")
    # Back-fill the graph from already-accepted invites (both directions), only where BOTH accounts
    # exist (the FK requires it) and it isn't a self-invite. ON CONFLICT keeps it idempotent.
    op.execute(
        """
        INSERT INTO ref.user_friends (user_id, friend_id, status)
        SELECT u.telegram_user_id, u.invited_by, 'accepted'
        FROM ref.users u
        JOIN ref.users iv ON iv.telegram_user_id = u.invited_by
        WHERE u.invited_by IS NOT NULL AND u.invited_by <> u.telegram_user_id
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO ref.user_friends (user_id, friend_id, status)
        SELECT u.invited_by, u.telegram_user_id, 'accepted'
        FROM ref.users u
        JOIN ref.users iv ON iv.telegram_user_id = u.invited_by
        WHERE u.invited_by IS NOT NULL AND u.invited_by <> u.telegram_user_id
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE ref.user_favorites DROP COLUMN IF EXISTS hidden_from_friends")
    op.execute("ALTER TABLE ref.users DROP COLUMN IF EXISTS photo_url")
    op.execute("ALTER TABLE ref.users DROP COLUMN IF EXISTS friends_private")
    op.execute("DROP INDEX IF EXISTS ref.ix_user_favorites_event")
    op.execute("DROP TABLE IF EXISTS ref.user_mutes")
    op.execute("DROP TABLE IF EXISTS ref.user_friends")
