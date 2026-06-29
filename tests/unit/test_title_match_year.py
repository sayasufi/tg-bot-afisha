"""A trailing edition year ("Ömankö Day" vs "Ömankö Day 2026") must not block a merge,
but two DIFFERENT years ("Лето 2025" vs "Лето 2026") must stay separate."""
from core.matching.title_match import same_event


def test_year_suffix_in_one_title_still_merges():
    assert same_event("Ömankö Day", "ÖMANKÖ DAY 2026") is True
    assert same_event("Фестиваль Лето", "Фестиваль Лето 2026") is True


def test_different_years_do_not_merge():
    assert same_event("Лето 2025", "Лето 2026") is False


def test_sequel_numbers_still_blocked():
    assert same_event("Часть 1", "Часть 2") is False
    assert same_event("Концерт 1", "Концерт 2") is False
