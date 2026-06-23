"""Smarter venue dedup: transliteration + cross-field (a venue's name living in the other's address)."""
from pipeline.dedup.venue_match import name_match_score


def test_alias_in_address_merges():
    # «ДК Альфа Кристалл» is named inside the address of «Alfa Only кинотеатр» — same place.
    s = name_match_score(
        "Alfa Only кинотеатр", "ДК Альфа Кристалл",
        addr_a="ДК «Альфа Кристалл», Самокатная ул., 4", addr_b="ул. Самокатная, 4, стр. 11",
    )
    assert s is not None


def test_single_common_token_does_not_merge():
    # Only "alfa" is shared and there's no corroborating address — must NOT merge.
    assert name_match_score("Alfa Bank", "Alfa Cafe") is None


def test_antonym_halls_stay_separate():
    assert name_match_score("Большой зал Консерватории", "Малый зал Консерватории") is None


def test_unrelated_neighbours_in_same_complex_stay_separate():
    assert name_match_score(
        "Krov Loft", "ДК Альфа Кристалл",
        addr_a="Самокатная, 4, стр. 32", addr_b="ул. Самокатная, 4, стр. 11",
    ) is None
