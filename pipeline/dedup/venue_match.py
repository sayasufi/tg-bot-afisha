"""Decide whether two venue *names* denote the same physical place.

Cross-source naming drift ("Космос" vs "Большой концертный зал «Космос»",
"МХТ им. Чехова" vs "МХТ имени А. П. Чехова") spawns a venue row per source for
one place, which splits a (correctly cross-source-merged) event into a pin per
venue. ``get_or_create_venue`` uses this at write time to reuse an existing
nearby venue instead of creating a near-duplicate; ``pipeline.maintenance.venues``
uses it to clean up the duplicates that already exist.

The proximity gate lives at the call site (only names of venues within a small
radius are compared); this module is the name half of the decision.
"""
import re

try:
    from rapidfuzz import fuzz
    # rapidfuzz 3.x dropped default processing → token_set_ratio turned case/punctuation-sensitive,
    # so "МХТ имени А. П. Чехова" vs "МХТ им. Чехова" dipped below STRONG_RATIO. Restore the
    # lowercase + strip-punctuation normalisation the thresholds were tuned against.
    from rapidfuzz.utils import default_process as _PROCESS
except Exception:  # pragma: no cover
    from difflib import SequenceMatcher

    _PROCESS = None

    class _FuzzFallback:
        @staticmethod
        def token_set_ratio(a: str, b: str, *, processor=None) -> float:
            if processor:
                a, b = processor(a), processor(b)
            return SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio() * 100

    fuzz = _FuzzFallback()

STRONG_RATIO = 85  # a name match this good is the same place on its own
COHOST_RATIO = 70  # a weaker match needs the duplicate-pin symptom (co-hosting)

_TOKEN_RE = re.compile(r"[0-9a-zа-я]+")

# Words that mark two *distinct* spaces in one building (Большой зал vs Малый зал
# Консерватории). When the names take opposite sides of such a pair they are
# different venues with separate schedules — never merge them.
_ANTONYMS = [
    ({"большой", "большая", "большое"}, {"малый", "малая", "малое"}),
    ({"новый", "новая", "новое", "new"}, {"старый", "старая", "старое", "old"}),
    ({"верхний", "верхняя"}, {"нижний", "нижняя"}),
    ({"левый", "левая"}, {"правый", "правая"}),
]


def tokens(s: str) -> set[str]:
    return set(_TOKEN_RE.findall((s or "").lower().replace("ё", "е")))


def contrasts(a: str, b: str) -> bool:
    ta, tb = tokens(a), tokens(b)
    return any((ta & x and tb & y) or (ta & y and tb & x) for x, y in _ANTONYMS)


def is_subset(a: str, b: str) -> bool:
    """One name's words are wholly contained in the other's, with at least one
    distinctive (>=4-char) shared word — "Театр им. Маяковского" inside "Театр
    им. Вл. Маяковского. Основная сцена". Rejects pairs that only share a generic
    location qualifier ("…Басманного района" vs "…на Басманной")."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return False
    small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return small <= big and any(len(t) >= 4 for t in small)


def name_match_score(a: str, b: str, co_host: bool = False) -> float | None:
    """token_set_ratio if the two nearby venue names should be treated as one
    place, else None. ``co_host`` is the duplicate-pin symptom (the two venues
    already share an event on the same date) — it relaxes the name bar. At write
    time co_host is unknown (the event isn't linked yet), so it defaults False
    and only strong names / structural containment reuse a venue."""
    if contrasts(a, b):  # different halls of one building — keep apart
        return None
    ratio = fuzz.token_set_ratio(a or "", b or "", processor=_PROCESS)
    if ratio >= STRONG_RATIO:
        return ratio
    if co_host and (is_subset(a, b) or ratio >= COHOST_RATIO):
        return ratio
    if not co_host and is_subset(a, b):
        return ratio
    return None
