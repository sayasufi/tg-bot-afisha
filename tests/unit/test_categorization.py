from core.domain.categorization import map_source_category


def test_yandex_art_type_is_exhibition():
    assert map_source_category(["art", "Выставка"], "yandex_afisha") == "exhibition"


def test_kudago_education_is_lecture():
    assert map_source_category(["education", "Лекции"], "kudago") == "lecture"


def test_excursions_is_tour():
    assert map_source_category(["excursions"], "yandex_afisha") == "tour"


def test_quest_is_its_own_category():
    assert map_source_category(["quest"], "yandex_afisha") == "quest"
    assert map_source_category(["квест"], "yandex_afisha") == "quest"


def test_quiz_and_entertainment_are_party():
    assert map_source_category(["квиз"], "kudago") == "party"
    assert map_source_category(["entertainment"], "kudago") == "party"


def test_kids_quest_stays_kids():
    # A children's quest is best found under «Детям», so kids outranks quest.
    assert map_source_category(["quest", "kids", "Детям"], "yandex_afisha") == "kids"


def test_kids_wins_over_primary_type():
    # The «Городская ферма» case: source primary type is art (exhibition) but it
    # is tagged for children — surface it under the family filter, never lecture.
    hints = ["art", "Выставка", "interactive", "Интерактив", "kids", "Детям"]
    assert map_source_category(hints, "yandex_afisha") == "kids"


def test_master_class_text_does_not_force_lecture():
    # Only structured labels drive the mapping; free-text mentions of a
    # master-class in the description never reach it.
    assert map_source_category(["art", "Выставка"], "yandex_afisha") == "exhibition"


def test_untyped_source_falls_back_to_llm():
    assert map_source_category(["other"], "yandex_afisha") is None
    assert map_source_category(["sport"], "yandex_afisha") is None
    assert map_source_category([], "kudago") is None


def test_telegram_always_defers_to_llm():
    # Telegram "tags" are LLM-extracted keywords, not trustworthy source labels.
    assert map_source_category(["concert", "Концерт"], "telegram_public:kuda_v_moskva") is None


def test_internal_category_marker_is_ignored():
    assert map_source_category(["category:lecture"], "yandex_afisha") is None
