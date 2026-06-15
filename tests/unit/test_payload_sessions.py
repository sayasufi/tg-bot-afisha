from datetime import datetime, timedelta, timezone

from core.db.repositories.ingestion import _payload_session_dates


def test_extracts_multiple_in_window_sessions() -> None:
    now = datetime.now(timezone.utc)
    s1 = int((now + timedelta(days=2, hours=21)).timestamp())
    s2 = int((now + timedelta(days=9, hours=21)).timestamp())
    payload = {"dates": [{"start": s1, "end": None}, {"start": s2, "end": None}]}
    sessions = _payload_session_dates(payload, now, now + timedelta(days=30))
    assert len(sessions) == 2
    assert [int(d.timestamp()) for d, _ in sessions] == [s1, s2]


def test_drops_out_of_window_and_dedups() -> None:
    now = datetime.now(timezone.utc)
    past = int((now - timedelta(days=10)).timestamp())
    soon = int((now + timedelta(days=1)).timestamp())
    far = int((now + timedelta(days=400)).timestamp())
    payload = {"dates": [{"start": past, "end": None}, {"start": soon}, {"start": soon}, {"start": far}]}
    sessions = _payload_session_dates(payload, now, now + timedelta(days=30))
    assert [int(d.timestamp()) for d, _ in sessions] == [soon]  # past+far dropped, dup collapsed


def test_keeps_ongoing_run_started_in_past() -> None:
    now = datetime.now(timezone.utc)
    start = int((now - timedelta(days=5)).timestamp())
    end = int((now + timedelta(days=20)).timestamp())
    payload = {"dates": [{"start": start, "end": end}]}
    sessions = _payload_session_dates(payload, now, now + timedelta(days=30))
    assert len(sessions) == 1  # ongoing exhibition span kept as one occurrence


def test_no_dates_returns_empty() -> None:
    now = datetime.now(timezone.utc)
    assert _payload_session_dates({"startDate": "2026-06-16"}, now, now + timedelta(days=30)) == []
    assert _payload_session_dates(None, now, now + timedelta(days=30)) == []
