from pipeline.dedup.scorer import score_candidate


def test_score_candidate_same_day_geo() -> None:
    score = score_candidate("Jazz Night", "Night Jazz", same_day=True, geo_close=True)
    assert score >= 0.79


def test_score_candidate_different() -> None:
    score = score_candidate("Metal Fest", "Kids Theater", same_day=False, geo_close=False)
    assert score < 0.7
