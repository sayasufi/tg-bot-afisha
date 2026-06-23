"""Genitive name forms ("Сергей"→"Сергея") must still read as the same word, so a bare-name event
merges with its qualified twin across sources."""
from pipeline.dedup.title_match import same_event, same_slot_title


def test_genitive_last_letter_swap_merges():
    # afisha_ru "Юбилейный концерт Сергея Трофимова" vs yandex "Сергей Трофимов" — one concert.
    assert same_event("Сергей Трофимов", "Юбилейный концерт Сергея Трофимова") is True
    assert same_slot_title("Сергей Трофимов", "Юбилейный концерт Сергея Трофимова") is True


def test_suffix_growth_still_merges():
    assert same_event("Владимир Пресняков", "Концерт Владимира Преснякова") is True


def test_different_people_do_not_merge():
    assert same_event("Сергей Иванов", "Андрей Петров") is False
