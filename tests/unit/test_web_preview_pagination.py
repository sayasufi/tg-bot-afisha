"""Backfill pagination keys off the lowest msg-id / oldest post on a page — pin that parse."""
from connectors.telegram.web_preview_connector import TelegramWebPreviewConnector


def test_page_floor_finds_lowest_id_and_oldest_dt():
    page = (
        '<div data-post="chan/100"><time datetime="2026-06-20T19:00:00+00:00">a</time></div>'
        '<div data-post="chan/95"><time datetime="2026-06-18T10:00:00+00:00">b</time></div>'
        '<div data-post="chan/97"><time datetime="2026-06-19T12:00:00+00:00">c</time></div>'
    )
    c = TelegramWebPreviewConnector("chan")
    page_min, oldest = c._page_floor(page)
    assert page_min == 95
    assert oldest is not None and oldest.date().isoformat() == "2026-06-18"


def test_page_floor_empty_page():
    assert TelegramWebPreviewConnector("chan")._page_floor("<html>nothing</html>") == (None, None)
