"""Tests for venue-name sameness — used at write time to reuse a venue and in the
merge/resplit passes. Cases are real production venues.
"""
import pytest

from pipeline.dedup.venue_match import contrasts, is_subset, name_match_score

try:
    import rapidfuzz  # noqa: F401

    HAS_RAPIDFUZZ = True
except Exception:  # pragma: no cover
    HAS_RAPIDFUZZ = False


def _match(a, b, co_host=False):
    return name_match_score(a, b, co_host=co_host) is not None


# --- structural subset (no rapidfuzz needed) -----------------------------------

@pytest.mark.parametrize("a,b", [
    ("Космос", "Большой концертный зал «Космос»"),
    ("Графит", "Центр городской культуры «Графит»"),
    ("На Басманной", "Театр на Басманной. Малая сцена"),
    ("Театр им. Маяковского", "Театр им. Вл. Маяковского. Основная сцена"),
])
def test_subset_venues_match(a, b):
    assert is_subset(a, b)
    assert _match(a, b) is True  # subset matches even without co-host


# --- antonym guard: different halls of one building stay distinct ---------------

@pytest.mark.parametrize("a,b", [
    ("Большой зал Консерватории", "Малый зал Консерватории"),
    ("Новая сцена", "Старая сцена"),
])
def test_contrasting_halls_never_merge(a, b):
    assert contrasts(a, b)
    assert _match(a, b) is False
    assert _match(a, b, co_host=True) is False


# --- co-host gate: weak name only merges with the duplicate-pin symptom ---------

def test_weak_name_needs_cohost():
    # "Планетарий" vs "Московский планетарий" is a subset -> matches regardless.
    assert _match("Планетарий", "Московский планетарий") is True


def test_unrelated_co_located_do_not_merge():
    # Both geocoded to the Басманny district centroid + share "Басманн", but are
    # different places — must not merge even when an over-merged event co-hosts.
    assert _match("Управа Басманного района", "Театр на Басманной", co_host=True) is False


def test_genuinely_different_names_do_not_merge():
    assert _match("В тишине", "Большая страна") is False


@pytest.mark.skipif(not HAS_RAPIDFUZZ, reason="ratio tier needs rapidfuzz")
@pytest.mark.parametrize("a,b", [
    ("МХТ имени А. П. Чехова", "МХТ им. Чехова"),
    ("Lюstra Bar", "Lustra Bar"),
    ("Католическая церковь Cвятой Ольги", "Католическая церковь святой Ольги"),
])
def test_strong_ratio_matches(a, b):
    assert _match(a, b) is True
