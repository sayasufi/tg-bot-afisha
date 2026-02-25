from pipeline.normalizer.extractors import parse_age, parse_dates, parse_price


def test_parse_price_range() -> None:
    text = "Tickets from 1500 RUB to 3500 RUB"
    pmin, pmax = parse_price(text)
    assert pmin == 1500
    assert pmax == 3500


def test_parse_age() -> None:
    assert parse_age("Event 18+") == "18+"
    assert parse_age("No limits") == ""


def test_parse_dates_any() -> None:
    start, end = parse_dates("2026-03-10 19:00")
    assert start is not None
    assert end is None
