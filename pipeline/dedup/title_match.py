"""Decide whether two event *titles* denote the same event.

The event dedup matched titles with a raw ``token_set_ratio``, which fails two
common cross-source cases:
  * transliteration — afisha.ru lists "Polnalyubvi", Yandex lists "Полналюбви";
    across alphabets the ratio is 0.
  * qualifier drift — "Света" vs "Света. Большой сольный концерт"; the bare title
    is a token-subset of the qualified one but scores far below the merge bar.

This module normalises both titles through a Cyrillic→Latin transliteration so
the two alphabets collapse to one key, then ranks a pair as the *same* event by:
  1. equal transliterated key (covers exact same-alphabet and cross-alphabet),
  2. one title's words wholly contained in the other's (with a distinctive,
     non-generic shared word), or
  3. a high transliterated token_set_ratio.
Guarded against merging sequels/parts that differ only by a number or ordinal
("Часть 1" vs "Часть 2") and against subset-merging on a purely generic word
("Концерт" vs "Концерт Баха"). The caller supplies the venue/day proximity.
"""
import re

try:
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover
    from difflib import SequenceMatcher

    class _FuzzFallback:
        @staticmethod
        def token_set_ratio(a: str, b: str) -> float:
            return SequenceMatcher(None, a.lower(), b.lower()).ratio() * 100

    fuzz = _FuzzFallback()

RATIO_AUTO = 92  # ratio safe enough to auto-merge
RATIO_FUZZY = 85  # ratio worth reviewing

# Cyrillic → Latin (BGN-ish; ё→e, ъ/ь dropped). Lets "Полналюбви" == "Polnalyubvi".
_CYR2LAT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e",
    "ю": "yu", "я": "ya",
})

_LAT_TOKEN = re.compile(r"[0-9a-z]+")
_CYR_TOKEN = re.compile(r"[0-9a-zа-я]+")
_NUM = re.compile(r"\d+")

# "Filler" words: too generic to anchor a subset merge on their own, and — when
# they are the only *extra* words on the longer title — descriptive enough that
# the two titles are still one event ("Света" vs "Света. Большой сольный концерт").
# A non-filler extra word (e.g. "Фигаро" in "Женитьба Фигаро") means a different
# work, so that subset is only a *review* candidate, never an auto-merge.
_FILLER = {
    # formats / event nouns
    "концерт", "концерты", "концертный", "концертная", "спектакль", "спектакли",
    "шоу", "экскурсия", "лекция", "выставка", "мастеркласс", "мастер", "класс",
    "вечер", "программа", "фестиваль", "квест", "комедия", "опера", "балет",
    "мюзикл", "премьера", "гастроли", "выступление", "вечеринка", "презентация",
    "show", "concert", "tour", "live", "лайв",
    # descriptors
    "большой", "большая", "большое", "сольный", "сольная", "сольное",
    "мультимедийный", "музыкальный", "авторский", "авторская", "юбилейный",
    "праздничный", "новогодний", "рождественский", "гала", "специальный",
    "творческий", "творческая", "тур", "стендап", "standup", "версия",
    "крыша", "крыше", "открытие", "закрытие", "бенефис",
    # prepositions / conjunctions
    "на", "в", "с", "по", "за", "до", "от", "для", "или", "и", "о", "об", "к", "у",
}


def _translit(s: str) -> str:
    return (s or "").lower().translate(_CYR2LAT)


def translit_tokens(s: str) -> list[str]:
    return _LAT_TOKEN.findall(_translit(s))


def translit_key(s: str) -> str:
    return "".join(translit_tokens(s))


def title_nkey(s: str) -> str:
    """Cyrillic-keeping normalised key, mirrored by a SQL expression in the dedup
    query: lower, ё→е, strip everything but letters/digits. Equal keys are the
    same title in the *same* alphabet (cross-alphabet needs translit_key)."""
    return re.sub(r"[^0-9a-zа-я]", "", (s or "").lower().replace("ё", "е"))


def _cyr_tokens(s: str) -> set[str]:
    return set(_CYR_TOKEN.findall((s or "").lower().replace("ё", "е")))


def _numbers(s: str) -> set[str]:
    return set(_NUM.findall(s or ""))


def same_event(a: str, b: str, level: str = "auto") -> bool:
    """True if the two titles denote the same event (caller has already checked
    venue/day proximity). ``level`` is the confidence demanded:

    - ``"safe"``  — identical transliterated key only: same title modulo alphabet,
      ё/е, punctuation, word order ("Селеба"/"Селеба", "Polnalyubvi"/"Полналюбви").
    - ``"auto"``  — also a token-subset whose *extra* words are pure filler
      ("Света" ⊂ "Света. Большой сольный концерт") or a very high ratio. Safe to
      merge automatically (write time + unattended self-heal).
    - ``"fuzzy"`` — also a subset with a distinctive extra word ("Женитьба" ⊂
      "Женитьба Фигаро") or a merely-high ratio. Higher recall but can be a
      different work, so these are surfaced for review, never auto-merged.
    """
    ka, kb = translit_key(a), translit_key(b)
    if not ka or not kb:
        return False
    # Sequels/parts: "Часть 1" vs "Часть 2", "День 1" vs "День 2" — never merge.
    if _numbers(a) != _numbers(b):
        return False
    if ka == kb:
        return True
    if level == "safe":
        return False

    ca, cb = _cyr_tokens(a), _cyr_tokens(b)
    small, big = (ca, cb) if len(ca) <= len(cb) else (cb, ca)
    # Token-subset anchored by a distinctive (>=4-char, non-filler) shared word.
    if small and small <= big and any(len(t) >= 4 and t not in _FILLER for t in small):
        extra = big - small
        extra_is_filler = all(t in _FILLER or len(t) <= 2 for t in extra)
        if level == "auto":
            if extra_is_filler:
                return True
        else:  # fuzzy: any distinctive subset is a review candidate
            return True

    ratio = fuzz.token_set_ratio(_translit(a), _translit(b))
    return ratio >= (RATIO_AUTO if level == "auto" else RATIO_FUZZY)
