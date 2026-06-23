"""The staleness sweep keys off the newest <time> on a t.me/s/ page — pin that parse."""
from pipeline.maintenance.telegram_health import _parse_newest


def test_parse_newest_picks_the_latest_post():
    html = (
        '<time datetime="2026-06-20T19:00:00+00:00">a</time>'
        '<div>...</div>'
        '<time datetime="2026-06-22T21:30:00+00:00">b</time>'
        '<time datetime="2026-05-01T10:00:00+00:00">c</time>'
    )
    dt = _parse_newest(html)
    assert dt is not None and dt.date().isoformat() == "2026-06-22"


def test_parse_newest_none_when_no_posts():
    assert _parse_newest("<html><body>preview with no time tags</body></html>") is None
