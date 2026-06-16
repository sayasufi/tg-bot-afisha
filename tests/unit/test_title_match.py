"""Tests for event-title sameness — the heart of cross-source event dedup.

Cases are drawn from real production duplicates and over-merges so a regression
here is a regression users would see on the map. The matcher has three confidence
levels: "safe" (exact/translit), "auto" (+ filler-only subsets, safe to merge
unattended) and "fuzzy" (+ distinctive subsets, review only).
"""
import pytest

from pipeline.dedup.title_match import same_event, same_slot_title, title_nkey, translit_key

try:
    import rapidfuzz  # noqa: F401

    HAS_RAPIDFUZZ = True
except Exception:  # pragma: no cover
    HAS_RAPIDFUZZ = False


# --- same-slot tier: token-subset at one venue + exact instant (no anchor word) --

@pytest.mark.parametrize("a,b", [
    # all-generic titles same_event rejects, but they are one show at one slot
    ("Большой стендап", "Большой стендап на Сретенке."),
    ("Стендап", "Стендап концерт"),
    ("Концерт", "Концерт Баха"),
    ("Polnalyubvi", "Полналюбви"),                          # cross-alphabet exact
])
def test_same_slot_merges_token_subset(a, b):
    assert same_slot_title(a, b) is True
    assert same_slot_title(b, a) is True


@pytest.mark.parametrize("a,b", [
    ("Большой стендап", "Женский стендап"),                 # different show, not subset
    ("Стендап 1", "Стендап 2"),                             # numbered, different tokens
    ("Лебединое озеро", "Щелкунчик"),                       # unrelated
])
def test_same_slot_rejects_non_subset(a, b):
    assert same_slot_title(a, b) is False


# --- safe tier: exact / transliterated / punctuation / order -------------------

@pytest.mark.parametrize("a,b", [
    ("Селеба", "Селеба"),
    ("Polnalyubvi", "Полналюбви"),                          # cross-alphabet translit
    ("polnalyubvi", "ПОЛНАЛЮБВИ"),                          # case + translit
    ("Принцесса против!", "Принцесса против"),              # punctuation
    ("Вишнёвый сад", "Вишневый сад"),                       # ё / е
    ("Jawa. Хиты «Сектор Газа»", "Jawa. Хиты Сектор Газа"), # quotes
])
def test_safe_tier_merges_at_every_level(a, b):
    for level in ("safe", "auto", "fuzzy"):
        assert same_event(a, b, level=level) is True


# --- auto tier: subset whose extra words are pure filler -----------------------

@pytest.mark.parametrize("a,b", [
    ("Света", "Света. Большой сольный концерт"),
    ("Мэйти", "Мэйти. Концерт на крыше"),
    ("Стас Старовойтов", "Стас Старовойтов Сольный концерт"),
    ("Расул Чабдаров", "Расул Чабдаров. Сольный концерт"),
    # genitive case: one source names the artist, another says "концерт <gen>"
    ("Владимир Пресняков", "концерт Владимира Преснякова"),
    ("Расул Чабдаров", "концерт Расула Чабдарова"),
])
def test_filler_subset_is_auto_not_safe(a, b):
    assert same_event(a, b, level="safe") is False
    assert same_event(a, b, level="auto") is True
    assert same_event(a, b, level="fuzzy") is True


def test_declension_does_not_overmerge_short_words():
    # внутреннее изменение (не суффикс) и короткие слова не должны схлопываться
    assert same_event("Кошка", "Кошки", level="fuzzy") is False
    assert same_event("Лев", "Льва", level="fuzzy") is False


# --- fuzzy tier only: distinctive extra word => review, never auto-merge --------

@pytest.mark.parametrize("a,b", [
    ("Женитьба", "Женитьба Фигаро"),               # a different work sharing a word
    ("Когда я боюсь", "Евгений Гришковец. Когда я боюсь"),  # artist prefix
])
def test_distinctive_subset_is_fuzzy_only(a, b):
    assert same_event(a, b, level="auto") is False
    assert same_event(a, b, level="fuzzy") is True


# --- never merge, at any level -------------------------------------------------

@pytest.mark.parametrize("a,b", [
    ("Часть 1", "Часть 2"),
    ("День 1", "День 2"),
    ("Концерт", "Концерт Баха"),          # generic anchor
    ("Спектакль", "Спектакль для детей"),
    ("Селеба", "Сталевары"),
    ("Кипелов", "Света"),
    ("Дракула", "Принцесса против!"),
])
def test_different_events_never_merge(a, b):
    assert same_event(a, b, level="fuzzy") is False


def test_empty_titles_do_not_merge():
    assert same_event("", "Света", level="fuzzy") is False
    assert same_event("", "", level="fuzzy") is False


# --- keys ----------------------------------------------------------------------

def test_translit_key_collapses_alphabets():
    assert translit_key("Полналюбви") == translit_key("Polnalyubvi")
    assert translit_key("Вишнёвый") == translit_key("Вишневый")


def test_title_nkey_strips_noise():
    assert title_nkey("Принцесса против!") == title_nkey("принцесса  против")
    assert title_nkey("Зелёный театр, ВДНХ") == "зеленыйтеатрвднх"


@pytest.mark.skipif(not HAS_RAPIDFUZZ, reason="ratio tier needs rapidfuzz")
def test_abbreviation_reorder_is_at_least_fuzzy():
    assert same_event("К 135-летию Сергея Прокофьева", "К 135-летию С. Прокофьева", level="fuzzy") is True
