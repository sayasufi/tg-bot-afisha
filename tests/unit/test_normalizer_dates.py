from pipeline.normalizer.rules import RuleBasedNormalizer


def test_ldjson_iso_dates():
    payload = {"title": "Концерт", "startDate": "2026-06-20T19:00:00+03:00"}
    candidate = RuleBasedNormalizer().normalize(payload, "Концерт")[0]
    assert candidate.date_start is not None
    assert candidate.date_start.year == 2026


def test_ldjson_natural_language_date_does_not_raise():
    payload = {"title": "Концерт", "startDate": "20 июня 2026 19:00"}
    candidate = RuleBasedNormalizer().normalize(payload, "Концерт")[0]
    assert candidate.date_start is not None
    assert candidate.date_start.year == 2026


def test_ldjson_garbage_date_does_not_raise():
    payload = {"title": "Концерт", "startDate": "definitely-not-a-date"}
    candidates = RuleBasedNormalizer().normalize(payload, "Концерт")
    assert candidates
