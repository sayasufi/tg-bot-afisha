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
