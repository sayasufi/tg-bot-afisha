import uuid
from datetime import datetime, timedelta, timezone

from apps.api.app.services.recommend import RecommendationService, _haversine_km

_MSK = timezone(timedelta(hours=3))
NOW = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
TODAY = NOW.astimezone(_MSK).date()
MOSCOW = (55.751, 37.618)


def _event(category, *, lat, lon, days=0, price=None, image=True, title="x", created_days_ago=1):
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
        "venue": "V",
        "venue_hours": None,
        "lat": lat,
        "lon": lon,
    }


def _svc():
    return RecommendationService(db=None)  # rail/score methods never touch the DB


def test_haversine_is_zero_at_same_point():
    assert _haversine_km(*MOSCOW, *MOSCOW) < 1e-6


def test_interest_and_proximity_rank_to_the_top():
    svc = _svc()
    near_interest = _event("concert", lat=55.752, lon=37.619, days=0, price=0)  # interest + near + today + free
    far_other = _event("theatre", lat=56.5, lon=38.5, days=10, price=500, image=False)
    scored = svc._score_all([near_interest, far_other], NOW, TODAY, MOSCOW[0], MOSCOW[1], {"concert"}, {})
    rails = svc._build_rails(scored, TODAY, has_loc=True, interests={"concert"}, per_rail=12)
    foryou = next(r for r in rails if r["key"] == "for_you")
    assert foryou["items"][0]["title"] == near_interest["title"]


def test_near_rail_sorted_by_distance_and_capped_radius():
    svc = _svc()
    close = _event("concert", lat=55.752, lon=37.619, title="close")
    mid = _event("concert", lat=55.80, lon=37.70, title="mid")
    far = _event("concert", lat=58.0, lon=40.0, title="far")  # >8km → excluded
    pool = [_event("concert", lat=55.76, lon=37.62, title=f"f{i}") for i in range(4)] + [close, mid, far]
    scored = svc._score_all(pool, NOW, TODAY, MOSCOW[0], MOSCOW[1], set(), {})
    rails = svc._build_rails(scored, TODAY, has_loc=True, interests=set(), per_rail=12)
    near = next(r for r in rails if r["key"] == "near")
    titles = [i["title"] for i in near["items"]]
    assert "far" not in titles
    assert titles[0] == "close"  # nearest first
    assert near["items"][0]["distance_m"] is not None


def test_free_rail_only_free_events():
    svc = _svc()
    pool = [_event("concert", lat=55.75, lon=37.62, price=0, title=f"free{i}") for i in range(4)]
    pool += [_event("theatre", lat=55.75, lon=37.62, price=500, title="paid")]
    scored = svc._score_all(pool, NOW, TODAY, MOSCOW[0], MOSCOW[1], set(), {})
    rails = svc._build_rails(scored, TODAY, has_loc=True, interests=set(), per_rail=12)
    free = next(r for r in rails if r["key"] == "free")
    assert all("free" in i["title"] for i in free["items"])


def test_sparse_themed_rail_is_dropped():
    svc = _svc()
    # Only 1 free event → the free rail (min 4) must not appear.
    pool = [_event("concert", lat=55.75, lon=37.62, price=500, title=f"p{i}") for i in range(6)]
    pool += [_event("concert", lat=55.75, lon=37.62, price=0, title="onlyfree")]
    scored = svc._score_all(pool, NOW, TODAY, MOSCOW[0], MOSCOW[1], set(), {})
    rails = svc._build_rails(scored, TODAY, has_loc=True, interests=set(), per_rail=12)
    assert not any(r["key"] == "free" for r in rails)
