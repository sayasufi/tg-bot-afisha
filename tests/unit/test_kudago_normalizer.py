from datetime import datetime, timedelta, timezone

from pipeline.normalizer.rules import RuleBasedNormalizer


def test_kudago_payload_normalization() -> None:
    payload = {
        "id": 123,
        "title": "Jazz Night",
        "description": "Live jazz evening",
        "dates": [{"start": 1773075600, "end": 1773082800}],
        "place": {"title": "Club A", "address": "Tverskaya 1"},
        "site_url": "https://kudago.com/event/123",
        "price": "1500 RUB",
        "age_restriction": 18,
        "images": [{"image": "https://img.example/1.jpg"}],
        "categories": [{"slug": "concert"}],
    }
    normalizer = RuleBasedNormalizer()

    results = normalizer.normalize(payload, "")

    assert len(results) == 1
    item = results[0]
    assert item.title == "Jazz Night"
    assert item.venue == "Club A"
    assert item.address == "Tverskaya 1"
    assert item.source_url == "https://kudago.com/event/123"
    assert item.age_limit == "18+"
    assert item.price_min == 1500
    assert "concert" in item.tags
    assert item.date_start is not None


def test_kudago_prefers_date_in_next_30_days() -> None:
    now = datetime.now(timezone.utc)
    old_start = int((now - timedelta(days=400)).timestamp())
    old_end = int((now - timedelta(days=399)).timestamp())
    in_window_start = int((now + timedelta(days=5)).timestamp())
    in_window_end = int((now + timedelta(days=5, hours=2)).timestamp())
    payload = {
        "title": "Late Date Selection",
        "description": "Should pick in-window date",
        "dates": [
            {"start": old_start, "end": old_end},
            {"start": in_window_start, "end": in_window_end},
        ],
        "place": {"title": "Venue X", "address": "Address X"},
    }
    normalizer = RuleBasedNormalizer()

    results = normalizer.normalize(payload, "")

    assert len(results) == 1
    item = results[0]
    assert item.date_start is not None
    assert int(item.date_start.timestamp()) == in_window_start


def test_kudago_uses_end_date_when_only_end_is_in_window() -> None:
    now = datetime.now(timezone.utc)
    old_start = int((now - timedelta(days=3)).timestamp())
    in_window_end = int((now + timedelta(days=2)).timestamp())
    payload = {
        "title": "Ongoing Event",
        "description": "Start is old, end is in window",
        "dates": [{"start": old_start, "end": in_window_end}],
        "place": {"title": "Venue Y", "address": "Address Y"},
    }
    normalizer = RuleBasedNormalizer()

    results = normalizer.normalize(payload, "")

    assert len(results) == 1
    item = results[0]
    assert item.date_start is not None
    assert int(item.date_start.timestamp()) == in_window_end
