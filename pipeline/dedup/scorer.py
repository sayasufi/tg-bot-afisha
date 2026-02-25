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


def score_candidate(title_a: str, title_b: str, same_day: bool, geo_close: bool) -> float:
    title_score = fuzz.token_set_ratio(title_a, title_b) / 100.0
    date_bonus = 0.2 if same_day else 0.0
    geo_bonus = 0.1 if geo_close else 0.0
    return min(1.0, title_score + date_bonus + geo_bonus)
