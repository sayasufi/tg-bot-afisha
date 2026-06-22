"""Timepad connector curation — the value of this source is in what it DROPS and COLLAPSES.

These pin the curation contract: junk/spam/placeless events are filtered, recurrences collapse to one
event with a start..end run, and the price string round-trips through the normalizer's parser.
"""
from datetime import datetime, timedelta, timezone

from connectors.web.timepad_connector import TimepadConnector
from pipeline.normalizer.extractors import parse_price_field

_MSK = timezone(timedelta(hours=3))


def _iso(days: int, hour: int = 19) -> str:
    dt = (datetime.now(_MSK) + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)
    return dt.isoformat()


def _event(**kw) -> dict:
    base = {
        "id": kw.get("id", 1),
        "name": "Событие",
        "starts_at": _iso(5),
        "ends_at": _iso(5, 21),
        "location": {"city": "Москва", "address": "ул. Тестовая, 1"},
        "organization": {"id": 100, "name": "Театр X"},
        "categories": [{"id": 1, "name": "Театры"}],
        "age_limit": "12",
        "poster_image": {"default_url": "https://img/x.jpg"},
        "description_short": "Описание",
        "url": "https://x.timepad.ru/event/1/",
        "registration_data": {"price_min": 500, "price_max": 1500},
        "moderation_status": "shown",
    }
    base.update(kw)
    return base


def _records(events):
    return TimepadConnector().build_records(events)


def test_price_text_round_trips_through_normalizer():
    c = TimepadConnector
    assert parse_price_field(c._price_text({"price_min": 500, "price_max": 1500})) == (500.0, 1500.0)
    assert parse_price_field(c._price_text({"price_min": 800, "price_max": 800})) == (800.0, 800.0)
    assert parse_price_field(c._price_text({"price_min": 0, "price_max": 0})) == (0.0, 0.0)  # free
    assert c._price_text(None) == ""  # unknown registration → blank, not "free"


def test_base_title_collapses_date_and_paren_variants():
    bt = TimepadConnector._base_title
    assert bt("Спектакль «Чайка» (22 июня)") == bt("Спектакль «Чайка» (2 июля)")


def test_junk_and_spam_are_dropped():
    events = [
        _event(id=1, name="Подарочный сертификат 5000"),                 # gift card
        _event(id=2, name="Консультация инженера-разработчика"),          # B2B
        _event(id=3, location={"city": "Москва"}),                        # placeless (no address)
        _event(id=4, organization={"id": 9, "name": "Gistoria (Гистория)"}),  # quest mill
        _event(id=5, moderation_status="hidden"),                         # not shown
    ]
    assert _records(events) == []


def test_timed_recurrences_collapse_to_concrete_next_session():
    # theatre = timed: collapse to ONE record showing the soonest CONCRETE date+time, NOT a multi-day range
    events = [
        _event(id=10, name="Спектакль «Чайка» (5 июля)", starts_at=_iso(5), ends_at=_iso(5, 21)),
        _event(id=11, name="Спектакль «Чайка» (8 июля)", starts_at=_iso(8), ends_at=_iso(8, 21)),
        _event(id=12, name="Спектакль «Чайка» (12 июля)", starts_at=_iso(12), ends_at=_iso(12, 21)),
    ]
    recs = _records(events)
    assert len(recs) == 1
    p = recs[0].payload
    assert p["sessions"] == 3
    assert p["startDate"][:10] == _iso(5)[:10]   # soonest session
    assert p["endDate"][:10] == _iso(5)[:10]     # SAME day → concrete, not a 5..12 range
    # stable id derived from organiser + base title, so re-fetches upsert the same raw
    assert recs[0].external_id.startswith("tp-")


def test_exhibition_is_allday_run_without_spurious_clock():
    # an exhibition spanning days → ALL-DAY open..close; the spurious opening clock is dropped
    [rec] = _records([_event(id=20, name="Выставка Кандинский",
                             categories=[{"id": 2, "name": "Выставки"}],
                             starts_at=_iso(5, 9), ends_at=_iso(40, 18))])
    p = rec.payload
    assert p["startDate"][:10] == _iso(5)[:10]
    assert p["startDate"][11:16] == "00:00"      # midnight — no confusing 09:00
    assert p["endDate"][:10] == _iso(40)[:10]     # run close


def test_lectures_and_workshops_dropped():
    events = [
        _event(id=30, name="Лекция о Врубеле"),
        _event(id=31, name="Мастер-класс по керамике"),
        _event(id=32, name="Открытый лекторий"),
    ]
    assert _records(events) == []


def test_clean_event_maps_all_fields():
    [rec] = _records([_event(id=20, name="Выставка Кандинский", categories=[{"id": 2, "name": "Выставки"}],
                             organization={"id": 7, "name": "Музей М"}, age_limit="0")]) or [None]
    p = rec.payload
    assert p["name"] == "Выставка Кандинский"
    assert p["place"] == {"title": "Музей М", "address": "ул. Тестовая, 1"}
    assert p["categories"] == ["Выставки"]
    assert p["age_restriction"] == 0
    assert p["poster_image"] == "https://img/x.jpg"
    assert parse_price_field(p["price"]) == (500.0, 1500.0)


def test_html_entities_unescaped():
    [rec] = _records([_event(id=30, name="Выставка &quot;Дали&amp;Пикассо&quot;")])
    assert rec.payload["name"] == 'Выставка "Дали&Пикассо"'
