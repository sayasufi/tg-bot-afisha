from dataclasses import dataclass

try:
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover
    from difflib import SequenceMatcher

    class _FuzzFallback:
        @staticmethod
        def token_set_ratio(a: str, b: str) -> float:
            return SequenceMatcher(None, a.lower(), b.lower()).ratio() * 100

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
    title_score = fuzz.token_set_ratio(title_a, title_b) / 100.0
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
