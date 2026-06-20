from datetime import date, timedelta

from connectors.web.afisha_ru_connector import _LOOKAHEAD_DAYS, AfishaRuConnector
from core.categorization import map_source_category

TODAY = date(2026, 6, 16)
# A date guaranteed past the listing horizon, derived from the real constant so the test stays valid
# whatever _LOOKAHEAD_DAYS is set to (it's now a full year).
OUT_OF_WINDOW = (TODAY + timedelta(days=_LOOKAHEAD_DAYS + 30)).isoformat()


def _conn() -> AfishaRuConnector:
    return AfishaRuConnector(city="msk")


def _tile(**over) -> dict:
    base = {
        "ID": 123,
        "Name": "Тестовый концерт",
        "Description": "<p>Очень <b>классно</b>&nbsp;&amp; громко</p>",
        "DisplayType": "концерт",
        "Type": "Concert",
        "Url": "/concert/test-123/",
        "ScheduleInfo": {"MinScheduleDate": "2026-06-20T19:30:00", "MaxScheduleDate": "2026-06-20T19:30:00", "MinPrice": 1500.0},
        "Image16x9": {"Url": "https://s.afisha.ru/a.jpg"},
        "Image1x1": {"Url": "https://s.afisha.ru/b.jpg"},
        "Genres": {"Links": [{"ShortName": "rock", "Name": "Рок"}]},
        "Notice": {"Place": {"Name": "Клуб", "Address": "ул. Тверская, 1", "Url": "/msk/place/klub-1/"}, "GeoPoint": None},
    }
    base.update(over)
    return base


# --- __nrp extraction (string/brace-aware) ----------------------------------

def test_extract_model_handles_braces_in_strings() -> None:
    html = (
        "<script>(window.__nrp = window.__nrp || {})['root'] = "
        '{"model":{"ScheduleWidget":{"Items":[],"Note":"a } brace \\" in text {nested}"}}};'
        "</script>"
    )
    model = AfishaRuConnector._extract_model(html)
    assert "ScheduleWidget" in model
    assert model["ScheduleWidget"]["Note"] == 'a } brace " in text {nested}'


def test_extract_model_missing_returns_empty() -> None:
    assert AfishaRuConnector._extract_model("<html>no nrp here</html>") == {}


# --- record building (wrapped + flat item shapes) ---------------------------

def test_build_records_wrapped_tile() -> None:
    recs = _conn()._build_records([{"Tile": _tile(), "Type": "Concert"}], "concert", TODAY)
    assert len(recs) == 1
    p = recs[0].payload
    assert recs[0].external_id == "123"
    assert p["title"] == "Тестовый концерт"
    assert p["description"] == "Очень классно & громко"  # html stripped + unescaped
    assert p["site_url"] == "https://www.afisha.ru/concert/test-123/"
    assert p["price"] == "от 1500 ₽" and p["is_free"] is False
    assert p["images"] == [{"image": "https://s.afisha.ru/a.jpg"}, {"image": "https://s.afisha.ru/b.jpg"}]
    assert {"slug": "concert"} in p["categories"]
    assert p["place"]["title"] == "Клуб" and p["place"]["address"] == "ул. Тверская, 1"
    assert p["dates"][0]["start_time"] == "19:30:00"


def test_build_records_flat_item() -> None:
    # Exhibitions/kids put the fields on the item itself (no Tile wrapper).
    recs = _conn()._build_records([_tile()], "concert", TODAY)
    assert len(recs) == 1 and recs[0].payload["title"] == "Тестовый концерт"


def test_build_records_skips_out_of_window_and_untitled() -> None:
    far = _tile(ScheduleInfo={"MinScheduleDate": f"{OUT_OF_WINDOW}T19:00:00", "MaxScheduleDate": f"{OUT_OF_WINDOW}T19:00:00"})
    assert _conn()._build_records([{"Tile": far}], "concert", TODAY) == []
    assert _conn()._build_records([{"Tile": _tile(Name=None)}], "concert", TODAY) == []


# --- dates --------------------------------------------------------------------

def test_dates_single_showtime_keeps_clock_time() -> None:
    rows = _conn()._build_dates({"MinScheduleDate": "2026-06-20T19:30:00", "MaxScheduleDate": "2026-06-20T19:30:00"}, None, TODAY)
    assert len(rows) == 1
    assert rows[0]["start_time"] == "19:30:00" and rows[0]["start_date"] == "2026-06-20"


def test_dates_ongoing_run_becomes_one_span() -> None:
    # A continuous run collapses to a single clamped span only for EXHIBITIONS — concerts/shows stay
    # discrete (a span would render as a misleading multi-month range).
    rows = _conn()._build_dates(
        {"MinScheduleDate": "2026-06-01T00:00:00", "MaxScheduleDate": "2026-12-31T00:00:00"}, None, TODAY, is_exhibition=True
    )
    assert len(rows) == 1
    # clamped to today (past start), open-ended to the run's end
    assert rows[0]["start_date"] == "2026-06-16"
    assert rows[0]["end"] is not None and rows[0]["start_time"] == "00:00:00"


def test_dates_empty_when_run_ended() -> None:
    assert _conn()._build_dates({"MinScheduleDate": "2025-01-01T00:00:00", "MaxScheduleDate": "2025-02-01T00:00:00"}, None, TODAY) == []


# --- price / place ------------------------------------------------------------

def test_price_free_and_unknown() -> None:
    assert _conn()._price({"MinPrice": 0}) == ("Бесплатно", True)
    assert _conn()._price({"MinPrice": None}) == ("", False)
    assert _conn()._price({"MinPrice": 990.0}) == ("от 990 ₽", False)


def test_place_reads_geopoint_when_present() -> None:
    notice = {"Place": {"Name": "Зал", "Address": "адрес"}, "GeoPoint": {"Latitude": 55.75, "Longitude": 37.62}}
    place = _conn()._place(notice)
    assert place["coords"] == {"lat": 55.75, "lon": 37.62}
    assert _conn()._place({"Place": {"Name": "Зал"}, "GeoPoint": None})["coords"] is None


# --- categorisation: the rubric hint drives our taxonomy ----------------------

def test_category_hints_map_to_our_taxonomy() -> None:
    # The rubric is authoritative: even with a mismatched DisplayType, the only
    # category hint emitted is the rubric slug, so it maps cleanly.
    for rubric, expected in [("concert", "concert"), ("theatre", "theatre"), ("exhibition", "exhibition"), ("standup", "standup")]:
        recs = _conn()._build_records([{"Tile": _tile(DisplayType="концерт")}], rubric, TODAY)
        assert recs[0].payload["categories"] == [{"slug": rubric}]
        hints = [h["slug"] if isinstance(h, dict) else h for h in recs[0].payload["categories"]]
        assert map_source_category(hints, "afisha_ru") == expected
