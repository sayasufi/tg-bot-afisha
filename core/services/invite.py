"""Signed «Пойдём?» invite tokens.

Without a signature the invite deep-link carries a bare `inviter_id` the client could forge, letting
anyone (a) DM-spam any bot user with «X идёт с тобой» by replaying their id, and (b) probe a victim's
taste via referral warm-start. The token is HMAC(event_id:inviter_id, bot_token) — only a link our own
share endpoint minted carries a valid one. 12 hex chars (48 bits) is infeasible to forge and fits
inside Telegram's 64-char start_param alongside the UUID + inviter id.
"""
import hashlib
import hmac

from core.config.settings import get_settings

_SIG_LEN = 12


def sign(event_id: str, inviter_id: int) -> str:
    key = (get_settings().telegram_bot_token or "okrest-dev-secret").encode()
    return hmac.new(key, f"{event_id}:{inviter_id}".encode(), hashlib.sha256).hexdigest()[:_SIG_LEN]


def verify(event_id: str, inviter_id: int | None, sig: str | None) -> bool:
    """True only for an inviter_id that was signed for THIS event by our own share endpoint."""
    if not inviter_id or not sig:
        return False
    return hmac.compare_digest(sign(event_id, int(inviter_id)), sig)


def sign_friend(inviter_id: int, ver: int = 0) -> str:
    """Signs a personal «add me as a friend» deep-link. Namespaced ('friend:') so a friend sig can never
    be replayed as an event-invite sig (or vice versa) — different namespaces hash differently. `ver` is
    the account's friend_link_ver, which the first successful add BUMPS — making the link SINGLE-USE: once
    consumed, its sig no longer verifies, so it can't be reused or broadcast. ver==0 keeps the LEGACY
    payload ('friend:<id>') so links minted before versioning existed stay valid until first used.
    HMAC(friend:<id>[:<ver>], bot_token), 12 hex chars."""
    key = (get_settings().telegram_bot_token or "okrest-dev-secret").encode()
    msg = f"friend:{inviter_id}" if not ver else f"friend:{inviter_id}:{ver}"
    return hmac.new(key, msg.encode(), hashlib.sha256).hexdigest()[:_SIG_LEN]


def verify_friend(inviter_id: int | None, sig: str | None, ver: int = 0) -> bool:
    """True only for an inviter_id whose friend-link we minted at version `ver`. The CALLER must pass the
    account's CURRENT friend_link_ver loaded from the DB (never a client-supplied value) — otherwise the
    single-use guarantee is bypassable by sending ver=0 to revive a consumed link."""
    if not inviter_id or not sig:
        return False
    return hmac.compare_digest(sign_friend(int(inviter_id), int(ver or 0)), sig)
