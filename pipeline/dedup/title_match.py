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

RATIO_SAME = 90  # transliterated token_set_ratio at/above which titles are one event

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

# Words too generic to anchor a subset merge on their own.
_GENERIC = {
    "концерт", "концерты", "спектакль", "шоу", "экскурсия", "лекция", "выставка",
    "мастеркласс", "мастер", "класс", "вечер", "программа", "фестиваль", "квест",
    "show", "concert", "tour", "тур", "стендап", "standup", "комедия", "опера",
    "балет", "мюзикл", "премьера", "гастроли", "спектакли",
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


def same_event(a: str, b: str, fuzzy: bool = True) -> bool:
    """True if the two titles denote the same event (caller has already checked
    venue/day proximity).

    With ``fuzzy=False`` only the *safe* tier counts: an identical transliterated
    key — same title modulo alphabet, ё/е, punctuation and word order of the same
    words ("Селеба"/"Селеба", "Polnalyubvi"/"Полналюбви"). With ``fuzzy=True`` the
    token-subset and high-ratio tiers are added ("Света" ⊂ "Света. Большой сольный
    концерт") — higher recall, but a subset can be a *different* work ("Женитьба"
    ⊂ "Женитьба Фигаро"), so fuzzy matches are meant to be reviewed, not trusted
    blindly for an irreversible bulk merge."""
    ka, kb = translit_key(a), translit_key(b)
    if not ka or not kb:
        return False
    # Sequels/parts: "Часть 1" vs "Часть 2", "День 1" vs "День 2" — never merge.
    if _numbers(a) != _numbers(b):
        return False
    if ka == kb:
        return True
    if not fuzzy:
        return False

    ta, tb = set(translit_tokens(a)), set(translit_tokens(b))
    small_lat, big_lat = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    # Token-subset: one title's words are wholly inside the other's, anchored by a
    # distinctive (>=4-char) shared word, and the shorter title is not purely
    # generic ("Света" inside "Света. Большой сольный концерт" — yes; "Концерт"
    # inside "Концерт Баха" — no).
    if small_lat <= big_lat and any(len(t) >= 4 for t in small_lat):
        shorter = a if len(ta) <= len(tb) else b
        if any(t not in _GENERIC for t in _cyr_tokens(shorter)):
            return True

    return fuzz.token_set_ratio(_translit(a), _translit(b)) >= RATIO_SAME
