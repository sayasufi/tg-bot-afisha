"""Map a structured source's own category/tag labels into our fixed taxonomy.

Yandex Afisha and KudaGo each expose a reliable primary category (Yandex
`event.type.code` → "concert"/"theatre"/"art"/…; KudaGo `categories` →
"exhibition"/"education"/"kids"/…). Trusting that label is far more accurate
than re-deriving the category from free text with the LLM, which was over-firing
``lecture`` on anything that merely mentioned a master-class (e.g. the «Городская
ферма» contact-zoo, tagged *Выставка/Детям* by the source, landed in *Лекции*).

So we decide the category deterministically from the source's labels and only
fall back to the LLM when the source gives nothing we recognise (the genuinely
untyped tail) or for free-text sources like Telegram.
"""

# A source label — slug OR human name, matched case-insensitively — → our category.
_LABEL_TO_CATEGORY: dict[str, str] = {
    # concerts / live music
    "concert": "concert", "концерт": "concert", "концерты": "concert",
    # theatre / opera / ballet / musical
    "theatre": "theatre", "theater": "theatre", "театр": "theatre",
    "спектакль": "theatre", "спектакли": "theatre",
    "опера": "theatre", "балет": "theatre", "мюзикл": "theatre",
    # exhibitions / museums (Yandex types art exhibitions as "art")
    "art": "exhibition", "exhibition": "exhibition", "выставка": "exhibition",
    "выставки": "exhibition", "photo": "exhibition", "museum": "exhibition", "музей": "exhibition",
    # cinema
    "cinema": "cinema", "кино": "cinema",
    # stand-up
    "standup": "standup", "стендап": "standup",
    # festivals / fairs / city holidays
    "festival": "festival", "фестиваль": "festival", "ярмарка": "festival",
    "holiday": "festival", "праздник": "festival",
    # lectures / education (KudaGo "education" is the legitimate lecture source)
    "education": "lecture", "lecture": "lecture", "лекция": "lecture", "лекции": "lecture",
    # tours / excursions / walks
    "tour": "tour", "excursions": "tour", "excursion": "tour",
    "экскурсия": "tour", "экскурсии": "tour", "прогулка": "tour",
    # parties / quizzes / quests / generic entertainment
    "party": "party", "вечеринка": "party", "вечеринки": "party",
    "quest": "party", "квест": "party", "квиз": "party",
    "entertainment": "party", "развлечения": "party",
    # kids
    "kids": "kids", "детям": "kids", "дети": "kids", "children": "kids",
}

# When a source carries several mappable labels, the most specific wins. `kids`
# is highest so a children's show/excursion/film surfaces under the family
# filter rather than being buried under theatre/tour/cinema.
_PRIORITY = (
    "kids", "standup", "concert", "theatre", "cinema",
    "exhibition", "festival", "tour", "lecture", "party",
)


def map_source_category(hints: list[str] | None, source_name: str = "") -> str | None:
    """Return our category for a structured source's labels, or None when the
    source gave nothing recognisable (the caller then asks the LLM).

    Free-text sources (Telegram) carry no trustworthy structured labels — their
    "tags" are LLM-extracted keywords — so they always fall through to the LLM.
    """
    if source_name.startswith("telegram"):
        return None
    if not hints:
        return None
    found: set[str] = set()
    for hint in hints:
        token = str(hint or "").strip().lower()
        if not token or token.startswith("category:"):
            continue
        category = _LABEL_TO_CATEGORY.get(token)
        if category:
            found.add(category)
    for category in _PRIORITY:
        if category in found:
            return category
    return None
