import pytest

from pipeline.dedup.scorer import (
    AUTO_MERGE_THRESHOLD,
    REVIEW_THRESHOLD,
    classify_match,
    score_candidate,
)

try:
    import rapidfuzz  # noqa: F401

    HAS_RAPIDFUZZ = True
except Exception:  # pragma: no cover
    # Without rapidfuzz the scorer falls back to difflib, which is NOT
    # token-order-insensitive — so token-set assertions only hold in prod.
    HAS_RAPIDFUZZ = False


def test_score_candidate_same_day_geo() -> None:
    score = score_candidate("Jazz Night", "Night Jazz", same_day=True, geo_close=True)
    assert score >= 0.79


def test_score_candidate_different() -> None:
    score = score_candidate("Metal Fest", "Kids Theater", same_day=False, geo_close=False)
    assert score < REVIEW_THRESHOLD


# --- score_candidate behaviour -------------------------------------------------

def test_identical_titles_score_full() -> None:
    # Identical title alone is 1.0; bonuses are capped, never overflow.
    assert score_candidate("Концерт оркестра", "Концерт оркестра", same_day=False, geo_close=False) == pytest.approx(1.0)
    assert score_candidate("Концерт оркестра", "Концерт оркестра", same_day=True, geo_close=True) == 1.0


@pytest.mark.skipif(not HAS_RAPIDFUZZ, reason="token-set matching needs rapidfuzz")
def test_token_order_is_ignored() -> None:
    # token_set_ratio is order-insensitive: reordered words still match high.
    assert score_candidate("Ночь джаза", "Джаза ночь", same_day=False, geo_close=False) >= 0.95


def test_bonuses_are_additive_and_capped() -> None:
    base = score_candidate("Spektakl A", "Totally Different B", same_day=False, geo_close=False)
    same_day = score_candidate("Spektakl A", "Totally Different B", same_day=True, geo_close=False)
    both = score_candidate("Spektakl A", "Totally Different B", same_day=True, geo_close=True)
    assert same_day == pytest.approx(base + 0.2, abs=1e-9)
    assert both == pytest.approx(base + 0.3, abs=1e-9)
    assert 0.0 <= base <= 1.0 and both <= 1.0


def test_same_day_pushes_near_duplicate_into_auto_merge() -> None:
    # A title typo on the same day at the same venue should auto-merge, not split.
    score = score_candidate("Лебединое озеро", "Лебединое озеро.", same_day=True, geo_close=True)
    assert classify_match(score) == "auto-merge"


# --- classify_match thresholds (single source of truth) ------------------------

def test_classify_exact_boundaries() -> None:
    assert classify_match(AUTO_MERGE_THRESHOLD) == "auto-merge"
    assert classify_match(REVIEW_THRESHOLD) == "needs-review"
    assert classify_match(1.0) == "auto-merge"
    assert classify_match(0.0) == "new-event"


def test_classify_just_below_boundaries() -> None:
    assert classify_match(AUTO_MERGE_THRESHOLD - 0.001) == "needs-review"
    assert classify_match(REVIEW_THRESHOLD - 0.001) == "new-event"


def test_thresholds_are_ordered() -> None:
    assert 0.0 < REVIEW_THRESHOLD < AUTO_MERGE_THRESHOLD <= 1.0
