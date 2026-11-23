"""The pipeline pushes tag/id filtering into libosmium (C++) and computes road
segments with numpy. These tests pin that the fast paths give the same
results as the plain-Python logic they replaced."""
import math

import osmium
import pytest
from shapely.geometry import box
from shapely.prepared import prep

from calculate_gaps import (DEFAULT_HIGHWAY_WEIGHT, EXCLUDED_HIGHWAYS, HIGHWAY_WEIGHTS,
                            DrivableRoadExtractor)
from calculate_mosque_sizes import MosqueSizeExtractor
from common import M_PER_DEG_LAT, is_worship_tagged, worship_tag_filter

TAG_CASES = [
    {"amenity": "place_of_worship"},
    {"amenity": "place_of_worship", "religion": "christian"},
    {"amenity": "mosque"},
    {"building": "mosque"},
    {"building": "mosque", "amenity": "school"},
    {"building": "yes", "religion": "muslim"},
    {"amenity": "school"},
    {"place_of_worship": "musalla"},
    {"name": "مسجد"},
]


def _opl_tags(tags):
    return ",".join(f"{k}={v}" for k, v in tags.items())


def test_worship_tag_filter_matches_is_worship_tagged(tmp_path):
    lines = [f"n{i + 1} v1 x46.{i} y24.{i} T{_opl_tags(t)}" for i, t in enumerate(TAG_CASES)]
    lines.append(f"n{len(TAG_CASES) + 1} v1 x46.9 y24.9 T")  # untagged
    path = tmp_path / "tags.opl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    passed = {n.id for n in osmium.FileProcessor(str(path), osmium.osm.NODE)
              .with_filter(worship_tag_filter())}
    expected = {i + 1 for i, t in enumerate(TAG_CASES) if is_worship_tagged(t)}
    assert passed == expected


def test_filtered_way_still_gets_untagged_node_locations(tmp_path):
    # The filter drops the untagged nodes, but pyosmium stores node locations
    # before filters run, so the mosque way must still get its geometry.
    path = tmp_path / "mosque.opl"
    path.write_text(
        "n1 v1 x46.0000 y24.0000 T\n"
        "n2 v1 x46.0010 y24.0000 T\n"
        "n3 v1 x46.0010 y24.0010 T\n"
        "n4 v1 x46.0000 y24.0010 T\n"
        "w10 v1 Tbuilding=mosque Nn1,n2,n3,n4,n1\n"
        "w11 v1 Tbuilding=house Nn1,n2,n3,n4,n1\n",
        encoding="utf-8")
    area = box(45, 23, 47, 25)
    ex = MosqueSizeExtractor(prep(area), area.bounds)
    ex.apply_file(str(path), locations=True, filters=[worship_tag_filter()])
    assert set(ex.sizes) == {"10"}
    assert ex.sizes["10"]["area_m2"] > 10_000


def _reference_segments(ways, bounds):
    """The per-segment Python loop calculate_gaps used before numpy."""
    minx, miny, maxx, maxy = bounds
    out = []
    for h_type, coords in ways:
        if h_type in EXCLUDED_HIGHWAYS or len(coords) < 2 or None in coords:
            continue
        weight = HIGHWAY_WEIGHTS.get(h_type, DEFAULT_HIGHWAY_WEIGHT)
        is_res = h_type in ("residential", "living_street")
        for c1, c2 in zip(coords, coords[1:]):
            lon = (c1[0] + c2[0]) / 2.0
            lat = (c1[1] + c2[1]) / 2.0
            if minx <= lon <= maxx and miny <= lat <= maxy:
                m = 111_320.0 * math.cos(math.radians(lat))
                seg = math.hypot((c2[0] - c1[0]) * m, (c2[1] - c1[1]) * M_PER_DEG_LAT)
                if seg > 0:
                    out.append((lon, lat, seg * weight, seg if is_res else 0.0))
    return out


def test_road_segments_match_reference_loop(tmp_path):
    nodes = {1: (46.0, 24.0), 2: (46.001, 24.0005), 3: (46.003, 24.002),
             4: (46.0031, 24.0021), 5: (48.5, 24.0), 6: (48.6, 24.1)}
    ways = [  # (id, highway, node refs)
        (10, "residential", [1, 2, 3]),
        (11, "primary", [3, 4, 4, 1]),        # repeated node -> zero-length segment
        (12, "motorway", [1, 3]),             # excluded class
        (13, "tertiary", [3, 5, 6]),          # partly outside the bbox
        (14, "residential", [1, 99]),         # node 99 missing -> whole way skipped
        (15, "living_street", [2, 2]),        # only zero-length
    ]
    lines = [f"n{i} v1 x{lon} y{lat} T" for i, (lon, lat) in nodes.items()]
    lines += [f"w{wid} v1 Thighway={h} N{','.join(f'n{r}' for r in refs)}" for wid, h, refs in ways]
    path = tmp_path / "roads.opl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    area = box(45.5, 23.5, 48.55, 24.5)
    ex = DrivableRoadExtractor(prep(area), area.bounds)
    ex.apply_file(str(path), locations=True, filters=[osmium.filter.KeyFilter("highway")])
    got = list(zip(*(a.tolist() for a in ex.road_segments())))

    ref = _reference_segments([(h, [nodes.get(r) for r in refs]) for _, h, refs in ways], area.bounds)
    assert len(got) == len(ref) > 0
    for g, r in zip(got, ref):
        assert g == pytest.approx(r, rel=1e-12, abs=1e-12)
