from apps.worker.worker.tasks.enrich import _coords_sane, _source_coords


def test_normal_moscow_coords_pass_through():
    assert _coords_sane(55.75, 37.62) == (55.75, 37.62)


def test_transposed_coords_are_swapped_back():
    # Yandex transposes lat/lon for some places → (37.55, 55.72) is really Moscow.
    assert _coords_sane(37.555975, 55.727785) == (55.727785, 37.555975)


def test_null_island_is_rejected():
    assert _coords_sane(0.0, 0.0) is None


def test_garbage_is_rejected():
    assert _coords_sane(999.0, -10.0) is None


def test_valid_but_foreign_coords_pass_the_guard():
    # Almaty is geographically valid (the region filter, not this guard, drops it).
    assert _coords_sane(43.26, 76.97) == (43.26, 76.97)


def test_source_coords_reads_and_sanitises_place():
    payload = {"place": {"coords": {"lat": 37.555975, "lon": 55.727785}}}
    assert _source_coords(payload) == (55.727785, 37.555975)
    assert _source_coords({"place": {"coords": {"lat": 0, "lon": 0}}}) is None
    assert _source_coords({}) is None
