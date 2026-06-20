"""Regression tests for the outbound-send idempotency contract (reminders + digest sweeps).

The Bot API answers 200-with-JSON even on a flood-wait, so the sweeps must distinguish a transient
429/5xx (RETRY — never stamp the idempotency ledger, or the message is lost) from a permanent
403/400 (STAMP once — the user blocked us / chat is gone). classify() encodes exactly that; a
regression that reclassifies 429 as 'permanent' would silently drop reminders.
"""
from apps.worker.worker.tasks.tg_send import PACE, classify, retry_after


def test_ok():
    assert classify({"ok": True}) == "ok"


def test_429_is_retry_never_stamped():
    assert classify({"ok": False, "error_code": 429}) == "retry"


def test_5xx_is_retry():
    assert classify({"ok": False, "error_code": 500}) == "retry"
    assert classify({"ok": False, "error_code": 502}) == "retry"


def test_permanent_failures_stamp_once():
    assert classify({"ok": False, "error_code": 403}) == "permanent"  # bot blocked
    assert classify({"ok": False, "error_code": 400}) == "permanent"  # chat not found


def test_unknown_failure_is_permanent_not_infinite_retry():
    assert classify({"ok": False}) == "permanent"


def test_retry_after_reads_parameter():
    assert retry_after({"parameters": {"retry_after": 7}}) == 7.0


def test_retry_after_default_and_clamp_and_garbage():
    assert retry_after({}) == 1.0
    assert retry_after({"parameters": {"retry_after": 9999}}) == 30.0  # clamped
    assert retry_after({"parameters": {"retry_after": "bad"}}) == 1.0


def test_pace_keeps_fanout_under_telegram_flood_limit():
    # The inter-send gap must be >= 1/30s so the fan-out stays under Telegram's ~30 msg/s threshold,
    # but not absurdly slow.
    assert 1 / 30 <= PACE < 0.1
