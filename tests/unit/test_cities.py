from core.domain.cities import DEFAULT_CITY, active_cities, city_by_slug, city_for_source_config


def test_default_and_active() -> None:
    assert DEFAULT_CITY.slug == "moscow"
    actives = active_cities()
    assert DEFAULT_CITY in actives
    assert all(c.active for c in actives)


def test_city_by_slug_falls_back() -> None:
    assert city_by_slug("moscow").slug == "moscow"
    assert city_by_slug("nope").slug == "moscow"
    assert city_by_slug(None).slug == "moscow"


def test_resolve_from_source_config() -> None:
    # Yandex stores `city`, KudaGo stores `location`; both resolve to the same city.
    assert city_for_source_config({"city": "moscow"}).slug == "moscow"
    assert city_for_source_config({"location": "msk"}).slug == "moscow"
    assert city_for_source_config({"city": "saint-petersburg"}).slug == "spb"
    assert city_for_source_config({"location": "spb"}).slug == "spb"
    assert city_for_source_config({}).slug == "moscow"  # default fallback
    assert city_for_source_config(None).slug == "moscow"
