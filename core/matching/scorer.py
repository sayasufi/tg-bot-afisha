from dataclasses import dataclass

try:
    from rapidfuzz import fuzz
    # rapidfuzz 3.x no longer applies a default processor, so token_set_ratio became
    # case/punctuation-SENSITIVE — "Ночь джаза" vs "Джаза ночь" scored 40 instead of 100. Restore the
    # lowercase + strip-non-alphanumeric normalisation the matching was designed around.
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


@dataclass
class MatchDecision:
    decision: str
    score: float
    matched_event_id: str | None = None


# Single source of truth for the dedup thresholds (also imported by the
# ingestion repository), so the boundaries are documented and unit-testable.
AUTO_MERGE_THRESHOLD = 0.87
REVIEW_THRESHOLD = 0.72


def score_candidate(title_a: str, title_b: str, same_day: bool, geo_close: bool) -> float:
    title_score = fuzz.token_set_ratio(title_a, title_b, processor=_PROCESS) / 100.0
    date_bonus = 0.2 if same_day else 0.0
    geo_bonus = 0.1 if geo_close else 0.0
    return min(1.0, title_score + date_bonus + geo_bonus)


def classify_match(score: float) -> str:
    """Map a candidate score to a dedup decision. Kept pure so the exact
    threshold behaviour can be tested without a database."""
    if score >= AUTO_MERGE_THRESHOLD:
        return "auto-merge"
    if score >= REVIEW_THRESHOLD:
        return "needs-review"
    return "new-event"
