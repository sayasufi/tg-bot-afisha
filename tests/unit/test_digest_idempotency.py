"""Regression test for the weekly-digest idempotency boundary.

A user is sent at most ONE digest per ISO week, gated by last_digest_sent_at < _week_start_utc(now).
If that boundary drifted (e.g. across the Sunday→Monday edge), a re-run / catch-up could re-send to
everyone. These pin the boundary to Monday 00:00 UTC so every day of a week maps to the same anchor.
"""
from datetime import datetime, timezone

from apps.worker.tasks.digest import _week_start_utc


def _ws(y, m, d, h=12):
    return _week_start_utc(datetime(y, m, d, h, tzinfo=timezone.utc))


def test_week_start_is_monday_midnight_utc():
    # 2026-06-20 is a Saturday → Monday of its ISO week is 2026-06-15.
    assert _ws(2026, 6, 20) == datetime(2026, 6, 15, tzinfo=timezone.utc)


def test_all_days_of_one_week_share_one_anchor():
    anchors = {_ws(2026, 6, d) for d in range(15, 22)}  # Mon 15 … Sun 21
    assert anchors == {datetime(2026, 6, 15, tzinfo=timezone.utc)}


def test_sunday_night_stays_in_same_week():
    # The boundary the audit flagged: Sunday 23:00 UTC must still anchor to the prior Monday.
    assert _ws(2026, 6, 21, 23) == datetime(2026, 6, 15, tzinfo=timezone.utc)


def test_new_week_advances_anchor():
    assert _ws(2026, 6, 22) == datetime(2026, 6, 22, tzinfo=timezone.utc)  # next Monday
