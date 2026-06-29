import math

from apps.api.services.events_service import EventQueryService

merge = EventQueryService._merge_clusters


def _px_gap(a, b, zoom):
    k = 256 * (2 ** zoom) / 360.0
    lat_scale = math.cos(math.radians(55.75))
    dlon = (a["lon"] - b["lon"]) * k
    dlat = (a["lat"] - b["lat"]) / lat_scale * k
    return math.hypot(dlon, dlat)


def test_far_apart_cells_are_kept_separate():
    cells = [
        {"lat": 55.75, "lon": 37.6, "count": 10},
        {"lat": 55.95, "lon": 38.2, "count": 5},
    ]
    out = merge(cells, zoom=11)
    assert len(out) == 2
    assert sum(c["count"] for c in out) == 15


def test_nearby_cells_merge_and_preserve_total():
    # Three cells within a few hundredths of a degree at city zoom -> one cluster.
    cells = [
        {"lat": 55.750, "lon": 37.600, "count": 100},
        {"lat": 55.752, "lon": 37.603, "count": 60},
        {"lat": 55.748, "lon": 37.598, "count": 40},
    ]
    out = merge(cells, zoom=11)
    assert len(out) == 1
    assert out[0]["count"] == 200
    # Weighted centroid stays inside the original spread.
    assert 55.748 <= out[0]["lat"] <= 55.752
    assert 37.598 <= out[0]["lon"] <= 37.603


def test_output_clusters_never_overlap():
    # A dense scatter of cells -> every surviving pair must sit >= the marker
    # footprint apart on screen (sep_px default 72, marker ~57px).
    cells = []
    for i in range(12):
        for j in range(12):
            cells.append({"lat": 55.70 + i * 0.004, "lon": 37.55 + j * 0.006, "count": i + j + 1})
    out = merge(cells, zoom=11)
    for a in range(len(out)):
        for b in range(a + 1, len(out)):
            assert _px_gap(out[a], out[b], 11) >= 57.0


def test_empty_input():
    assert merge([], zoom=11) == []
