from datetime import datetime, timedelta, timezone

from connectors.telegram.web_preview_connector import TelegramWebPreviewConnector

_NOW = datetime.now(timezone.utc)
_RECENT = _NOW.replace(microsecond=0).isoformat()
_OLD = (_NOW - timedelta(days=30)).replace(microsecond=0).isoformat()

_PAGE = f"""
<div class="tgme_widget_message js-widget_message" data-post="kuda_v_moskva/101" data-view="x">
  <a class="tgme_widget_message_photo_wrap" style="width:100%;background-image:url('https://cdn4.cdn-telegram.org/file/photo101.jpg')"></a>
  <div class="tgme_widget_message_text js-message_text" dir="auto">
    Концерт в саду «Эрмитаж»!<br/>Вход <b>свободный</b> &amp; 18+ #концерт #музыка
    <a href="https://example.com/tickets">Билеты</a>
  </div>
  <time datetime="{_RECENT}">12:00</time>
</div>
<div class="tgme_widget_message js-widget_message" data-post="kuda_v_moskva/100">
  <div class="tgme_widget_message_text js-message_text" dir="auto">Старый пост</div>
  <time datetime="{_OLD}">12:00</time>
</div>
<div class="tgme_widget_message service_message" data-post="kuda_v_moskva/99">
  <time datetime="{_RECENT}">12:00</time>
</div>
"""


def _parse(min_id: int = 0):
    connector = TelegramWebPreviewConnector("@Kuda_V_Moskva")
    cutoff = _NOW - timedelta(days=7)
    return connector.parse_page(_PAGE, min_id=min_id, cutoff=cutoff)


def test_parses_recent_text_message():
    records = _parse()
    assert len(records) == 1
    rec = records[0]
    assert rec.external_id == "kuda_v_moskva:101"
    assert rec.payload["title"].startswith("Концерт в саду «Эрмитаж»")
    assert "Вход свободный & 18+" in rec.payload["description"]
    assert rec.payload["site_url"] == "https://t.me/kuda_v_moskva/101"
    assert rec.payload["images"] == ["https://cdn4.cdn-telegram.org/file/photo101.jpg"]
    assert "концерт" in rec.payload["tags"]


def test_old_posts_and_service_messages_skipped():
    records = _parse()
    ids = [rec.payload["id"] for rec in records]
    assert 100 not in ids  # older than lookback
    assert 99 not in ids  # service message without text


def test_min_id_cursor_filters():
    assert _parse(min_id=101) == []
