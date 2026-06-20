"""Shared Telegram-send helpers for the outbound sweeps (reminders + digest).

The Bot API returns 200 with a JSON envelope even for failures, so httpx never raises on a
flood-wait (429) — the sweeps used to treat ANY non-thrown response as "delivered" and stamp the
idempotency ledger, silently dropping the message. These helpers classify the response so a 429 /
5xx is RETRIED (never stamped) while a genuine permanent failure (403 blocked, 400 chat-not-found)
is stamped once. PACE keeps the fan-out under Telegram's ~30 msg/s threshold so we don't provoke
the 429 in the first place.
"""

# ~28 msg/s — a small gap between sends keeps a digest/reminder fan-out under Telegram's flood limit.
PACE = 0.035


def classify(data: dict) -> str:
    """'ok' | 'retry' (429 or 5xx — transient, do NOT stamp) | 'permanent' (403/400 — stamp once)."""
    if data.get("ok"):
        return "ok"
    code = data.get("error_code")
    if code == 429 or (isinstance(code, int) and code >= 500):
        return "retry"
    return "permanent"


def retry_after(data: dict, default: float = 1.0, cap: float = 30.0) -> float:
    """Seconds Telegram asks us to wait (parameters.retry_after), clamped so one send can't stall a run."""
    try:
        val = float((data.get("parameters") or {}).get("retry_after") or default)
    except (TypeError, ValueError):
        val = default
    return max(0.0, min(val, cap))
