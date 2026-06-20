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
