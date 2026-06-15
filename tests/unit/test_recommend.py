import uuid
from datetime import datetime, timedelta, timezone

from apps.api.app.services.recommend import RecommendationService, _haversine_km

_MSK = timezone(timedelta(hours=3))
NOW = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
TODAY = NOW.astimezone(_MSK).date()
HOUR = NOW.astimezone(_MSK).hour
MOSCOW = (55.751, 37.618)


def _event(category, *, lat, lon, days=0, price=None, image=True, title="x", venue=None, created_days_ago=1):
    start = NOW + timedelta(days=days)
    return {
        "event_id": uuid.uuid4(),
        "title": title,
        "category": category,
        "created_at": NOW - timedelta(days=created_days_ago),
        "cached_image_url": "http://img/x.jpg" if image else "",
        "primary_image_url": "",
        "date_start": start,
        "date_end": start + timedelta(hours=2),
        "price_min": price,
        "venue": venue or f"venue-{title}",
        "venue_hours": None,
        "lat": lat,
        "lon": lon,
    }


def _svc():
    return RecommendationService(db=None)  # scoring/rail methods never touch the DB


def _score(svc, pool, affinity):
    return svc._score_all(pool, NOW, TODAY, HOUR, MOSCOW[0], MOSCOW[1], affinity, {})


def test_haversine_is_zero_at_same_point():
    assert _haversine_km(*MOSCOW, *MOSCOW) < 1e-6


def test_affinity_blends_favourites_and_behaviour():
    aff = RecommendationService._affinity({"concert"}, ["exhibition", "exhibition", "tour"])
    assert aff["concert"] == 1.0  # explicit favourite
    assert aff["exhibition"] > aff["tour"] > 0.0  # opened more often → higher
    assert "kids" not in aff


def test_affinity_ranks_to_the_top():
    svc = _svc()
    liked = _event("concert", lat=55.752, lon=37.619, days=0, price=0, title="liked")
    other = _event("theatre", lat=56.5, lon=38.5, days=10, price=500, image=False, title="other")
    scored = _score(svc, [liked, other], {"concert": 1.0})
    rails = svc._build_rails(scored, TODAY, True, {"concert": 1.0}, 12)
    foryou = next(r for r in rails if r["key"] == "for_you")
    assert foryou["items"][0]["title"] == "liked"


def test_for_you_is_diverse_across_categories_and_venues():
    svc = _svc()
    # A diverse pool (enough categories to fill 12) with 8 concerts at ONE venue:
    # for_you must cap concerts (≤3 per category, ≤2 per venue) and spread out.
    pool = [_event("concert", lat=55.75, lon=37.62, title=f"c{i}", venue="hall") for i in range(8)]
    for cat in ("exhibition", "tour", "kids", "theatre"):
        pool += [_event(cat, lat=55.75, lon=37.62, title=f"{cat}{i}") for i in range(4)]
    foryou = next(r for r in svc._build_rails(_score(svc, pool, {}), TODAY, True, {}, 12) if r["key"] == "for_you")
    cats = [i["category"] for i in foryou["items"]]
    assert cats.count("concert") <= 2  # same-venue concerts capped at 2
    assert len(set(cats)) >= 4  # a real cross-section


def test_explore_rail_excludes_your_usual_categories():
    svc = _svc()
    pool = [_event("concert", lat=55.75, lon=37.62, title=f"c{i}") for i in range(6)]
    pool += [_event("exhibition", lat=55.75, lon=37.62, title=f"e{i}") for i in range(6)]
    scored = _score(svc, pool, {"concert": 1.0})
    rails = svc._build_rails(scored, TODAY, True, {"concert": 1.0}, 12)
    explore = next((r for r in rails if r["key"] == "explore"), None)
    assert explore is not None
    assert all(i["category"] != "concert" for i in explore["items"])


def test_near_rail_sorted_by_distance_and_capped_radius():
    svc = _svc()
    pool = [_event("concert", lat=55.76, lon=37.62, title=f"f{i}") for i in range(4)]
    pool += [_event("concert", lat=55.752, lon=37.619, title="close"), _event("concert", lat=58.0, lon=40.0, title="far")]
    scored = _score(svc, pool, {})
    near = next(r for r in svc._build_rails(scored, TODAY, True, {}, 12) if r["key"] == "near")
    titles = [i["title"] for i in near["items"]]
    assert "far" not in titles and titles[0] == "close"


def test_no_interests_rail_anymore():
    svc = _svc()
    pool = [_event("concert", lat=55.75, lon=37.62, title=f"c{i}") for i in range(6)]
    rails = svc._build_rails(_score(svc, pool, {"concert": 1.0}), TODAY, True, {"concert": 1.0}, 12)
    assert not any(r["key"] == "interests" for r in rails)
