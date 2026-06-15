import asyncio
from datetime import date

from connectors.web.yandex_afisha_connector import YandexAfishaConnector
from pipeline.normalizer.rules import RuleBasedNormalizer

TODAY = date(2026, 6, 15)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payload):
        self._payload = payload

    async def post(self, *args, **kwargs):
        return _FakeResponse(self._payload)


def _conn() -> YandexAfishaConnector:
    return YandexAfishaConnector(city="moscow", page_size=10, with_descriptions=False)


# --- price (kopecks -> RU text field) ----------------------------------------


def test_price_converts_kopecks_to_rub_text() -> None:
    assert _conn()._price([{"price": {"currency": "rub", "min": 300000, "max": 1500000}}]) == ("от 3000 до 15000 ₽", False)
    assert _conn()._price([{"price": {"currency": "rub", "min": 250000, "max": 250000}}]) == ("2500 ₽", False)


def test_price_free_and_missing() -> None:
    assert _conn()._price([{"price": {"currency": "rub", "min": 0, "max": 0}}]) == ("Бесплатно", True)
    assert _conn()._price([]) == ("", False)
    assert _conn()._price([{"price": {"min": None, "max": None}}]) == ("", False)


def test_price_text_round_trips_through_normalizer() -> None:
    text, _ = _conn()._price([{"price": {"currency": "rub", "min": 150000, "max": 320000}}])
    payload = {"title": "X", "price": text, "place": {"title": "V", "address": "A"}}
    item = RuleBasedNormalizer().normalize(payload, "")[0]
    assert (item.price_min, item.price_max) == (1500.0, 3200.0)


# --- dates -------------------------------------------------------------------


def test_dates_single_showtime_keeps_clock() -> None:
    rows = _conn()._build_dates(
        {"dates": ["2026-06-26"], "regularity": {"singleShowtime": "2026-06-26T20:00:00"}}, TODAY
    )
    assert len(rows) == 1
    assert rows[0]["start_time"] == "20:00:00"
    assert rows[0]["end"] is None


def test_dates_all_day_uses_midnight_placeholder() -> None:
    rows = _conn()._build_dates({"dates": ["2026-06-20", "2026-06-21"], "regularity": {}}, TODAY)
    assert all(r["start_time"] == "00:00:00" and r["end"] is not None for r in rows)


def test_dates_filters_outside_window_and_caps() -> None:
    rows = _conn()._build_dates({"dates": ["2026-06-01", "2026-06-20", "2027-01-01"], "regularity": {}}, TODAY)
    assert [r["start_date"] for r in rows] == ["2026-06-20"]


def test_dates_permanent_is_open_ended() -> None:
    rows = _conn()._build_dates({"permanent": True, "dateStarted": "2020-01-01"}, TODAY)
    assert len(rows) == 1 and rows[0]["end"] > _conn()._date_to_ts("2090-01-01")


def test_dates_span_fallback_when_no_discrete_dates() -> None:
    rows = _conn()._build_dates({"dates": [], "dateStarted": "2026-01-01", "dateEnd": "2026-12-31"}, TODAY)
    assert len(rows) == 1 and rows[0]["start_time"] == "00:00:00" and rows[0]["end"] is not None


def test_dates_empty_when_nothing_usable() -> None:
    assert _conn()._build_dates({"dates": []}, TODAY) == []


def test_dates_date_only_showtime_falls_through_to_all_day() -> None:
    # A malformed date-only singleShowtime must NOT become a fake 00:00 showtime.
    rows = _conn()._build_dates({"dates": ["2026-06-20"], "regularity": {"singleShowtime": "2026-06-20"}}, TODAY)
    assert len(rows) == 1
    assert rows[0]["start_time"] == "00:00:00"
    assert rows[0]["end"] is not None  # all-day row carries an end-of-day, not None


def test_dates_permanent_missing_start_is_stable() -> None:
    # Missing dateStarted must yield a STABLE (deterministic) start for dedup, not now().
    a = _conn()._build_dates({"permanent": True}, TODAY)
    b = _conn()._build_dates({"permanent": True}, TODAY)
    assert a == b
    assert a[0]["start"] == _conn()._date_to_ts("2000-01-01")


# --- venue resolution --------------------------------------------------------


def test_place_only_place() -> None:
    place = _conn()._place_of(
        {"onlyPlace": {"id": "1", "title": "Hall", "address": "Arbat 1", "coordinates": {"latitude": 55.7, "longitude": 37.6}, "metro": [{"name": "Arbatskaya"}]}}
    )
    assert place["title"] == "Hall"
    assert place["coords"] == {"lat": 55.7, "lon": 37.6}
    assert place["subway"] == "Arbatskaya"


def test_place_falls_back_to_one_of_places_single_dict() -> None:
    place = _conn()._place_of(
        {"onlyPlace": None, "oneOfPlaces": {"id": "2", "title": "Bar", "coordinates": {"latitude": 55.0, "longitude": 37.0}}}
    )
    assert place["title"] == "Bar" and place["coords"] == {"lat": 55.0, "lon": 37.0}


def test_place_none_when_absent() -> None:
    assert _conn()._place_of({"onlyPlace": None, "oneOfPlaces": None}) is None


def test_place_tolerates_malformed_coordinates_and_metro() -> None:
    # Non-dict coordinates / non-list metro must not crash; coords degrade to None.
    place = _conn()._place({"id": "1", "title": "X", "coordinates": "55.7,37.6", "metro": "Arbatskaya"})
    assert place is not None
    assert place["coords"] is None
    assert place["subway"] is None


# --- transport / error handling ----------------------------------------------


def test_fetch_page_raises_on_graphql_errors() -> None:
    session = _FakeSession({"errors": [{"message": "rate limited"}], "data": None})
    try:
        asyncio.run(_conn()._fetch_page(session, 0, TODAY))
        raise AssertionError("expected RuntimeError on GraphQL errors")
    except RuntimeError as exc:
        assert "rate limited" in str(exc)


def test_fetch_page_tolerates_non_dict_actual_events() -> None:
    session = _FakeSession({"data": {"actualEvents": "unexpected"}})
    records, total = asyncio.run(_conn()._fetch_page(session, 0, TODAY))
    assert records == [] and total == 0


# --- html + full record mapping ---------------------------------------------


def test_strip_html() -> None:
    assert _conn()._strip_html('<a href="x">Hi</a>&nbsp;&amp; more\n\ntext') == "Hi & more text"


def test_build_records_maps_to_pipeline_payload_end_to_end() -> None:
    items = [
        {
            "event": {
                "id": "abc",
                "url": "/moscow/concert/x",
                "title": "Концерт X",
                "argument": "<b>Хедлайнер</b> вечера",
                "contentRating": "16+",
                "type": {"code": "concert", "name": "Концерт"},
                "tags": [{"code": "rock", "name": "Рок"}],
                "image": {"cover": {"url": "https://img/cover.jpg"}, "orig": {"url": "https://img/orig.jpg"}},
                "tickets": [{"price": {"currency": "rub", "min": 200000, "max": 500000}}],
            },
            "scheduleInfo": {
                "dates": ["2026-06-20"],
                "dateStarted": "2026-06-20",
                "dateEnd": "2026-06-20",
                "permanent": False,
                "regularity": {"singleShowtime": "2026-06-20T19:00:00"},
                "onlyPlace": {"id": "p1", "title": "Лужники", "address": "ул. Лужники, 24", "coordinates": {"latitude": 55.71, "longitude": 37.55}, "metro": [{"name": "Спортивная"}]},
            },
        }
    ]
    records = _conn()._build_records(items, TODAY)
    assert len(records) == 1
    rec = records[0]
    assert rec.external_id == "abc"
    payload = rec.payload
    # description from argument is HTML-stripped
    assert payload["description"] == "Хедлайнер вечера"
    # exact source coords are exposed where enrich expects them
    assert payload["place"]["coords"] == {"lat": 55.71, "lon": 37.55}
    # category + tag hints carry both machine code and human name
    assert {"slug": "concert"} in payload["categories"] and "Концерт" in payload["categories"]

    item = RuleBasedNormalizer().normalize(payload, rec.raw_text)[0]
    assert item.title == "Концерт X"
    assert item.venue == "Лужники"
    assert item.address == "ул. Лужники, 24"
    assert item.age_limit == "16+"
    assert (item.price_min, item.price_max) == (2000.0, 5000.0)
    assert item.source_url == "https://afisha.yandex.ru/moscow/concert/x"
    assert item.images and item.images[0] == "https://img/cover.jpg"
    assert "concert" in item.tags and "rock" in item.tags
    assert item.date_start is not None
