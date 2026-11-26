import json
import math
import os
import sys
import time

import numpy as np
import osmium
import shapely
from shapely.geometry import Point
from shapely.strtree import STRtree

from common import (BASE_DIR, M_PER_DEG_LAT, M_PER_DEG_LON, find_pbf, load_boundary,
                    update_summary, write_json)

# Through-traffic road classes are downweighted: OSM fragments them into many
# short tagged segments (speed/lane/name changes), which inflates apparent
# density in cities without indicating where people actually live.
# Exclude non-residential and through-transit/infrastructure ways
EXCLUDED_HIGHWAYS = {
    'footway', 'path', 'steps', 'cycleway', 'pedestrian',
    'bridleway', 'corridor', 'platform', 'elevator',
    'proposed', 'construction', 'abandoned', 'escape', 'sidewalk',
    'track', 'service', 'motorway', 'motorway_link', 'trunk', 'trunk_link',
    'raceway', 'bus_guideway'
}

HIGHWAY_WEIGHTS = {
    'primary': 0.3,
    'primary_link': 0.3,
    'secondary': 0.6,
    'secondary_link': 0.6,
    'tertiary': 0.8,
    'tertiary_link': 0.8,
}
DEFAULT_HIGHWAY_WEIGHT = 1.0


class DrivableRoadExtractor(osmium.SimpleHandler):
    """Collects drivable road geometry. The per-way callback only asks
    libosmium (C++) for the way's WKB; segment midpoints and lengths are then
    computed for all ~2M roads at once with numpy in road_segments(). Reading
    each node's lon/lat from Python (~9M accesses) used to dominate this step.
    """

    def __init__(self, boundary_prep, bounds):
        super().__init__()
        self.boundary_prep = boundary_prep
        self.minx, self.miny, self.maxx, self.maxy = bounds
        self._wkb = osmium.geom.WKBFactory()
        self.wkbs = []
        self.weights = []
        self.residential = []

    def way(self, w):
        h_type = w.tags.get('highway')
        if h_type is None or h_type in EXCLUDED_HIGHWAYS:
            return
        try:
            # Drops repeated consecutive nodes; those only formed zero-length
            # segments, which are skipped anyway.
            wkb = self._wkb.create_linestring(w)
        except (osmium.InvalidLocationError, RuntimeError):
            return  # unresolved node, or fewer than 2 distinct points
        self.wkbs.append(wkb)
        self.weights.append(HIGHWAY_WEIGHTS.get(h_type, DEFAULT_HIGHWAY_WEIGHT))
        self.residential.append(h_type in ('residential', 'living_street'))

    def road_segments(self):
        """Returns (seg_lon, seg_lat, weighted_length_m, residential_length_m)
        arrays, one entry per non-zero-length segment whose midpoint lies in
        the boundary's bbox, in file order."""
        # WKBFactory emits hex WKB: byte order (01 = little-endian), geometry
        # type (02000000 = LineString), uint32 point count, then lon/lat
        # float64 pairs. Decoding the coordinates directly is much faster than
        # shapely.from_wkb on ~1M hex strings.
        header = "0102000000"
        if not all(h.startswith(header) for h in self.wkbs):
            raise RuntimeError("unexpected WKB layout from osmium.geom.WKBFactory")
        arrays = [np.frombuffer(bytes.fromhex(h), dtype="<f8", offset=9) for h in self.wkbs]
        n_points = np.fromiter((len(a) // 2 for a in arrays), dtype=np.int64, count=len(arrays))
        coords = (np.concatenate(arrays) if arrays else np.zeros(0)).reshape(-1, 2)
        way_idx = np.repeat(np.arange(len(arrays)), n_points)
        same_way = way_idx[1:] == way_idx[:-1]
        c1 = coords[:-1][same_way]
        c2 = coords[1:][same_way]
        way_idx = way_idx[:-1][same_way]

        seg_lon = (c1[:, 0] + c2[:, 0]) / 2.0
        seg_lat = (c1[:, 1] + c2[:, 1]) / 2.0
        m_per_deg_lon_local = 111_320.0 * np.cos(np.radians(seg_lat))
        dx = (c2[:, 0] - c1[:, 0]) * m_per_deg_lon_local
        dy = (c2[:, 1] - c1[:, 1]) * M_PER_DEG_LAT
        seg_len = np.hypot(dx, dy)

        keep = ((self.minx <= seg_lon) & (seg_lon <= self.maxx)
                & (self.miny <= seg_lat) & (seg_lat <= self.maxy) & (seg_len > 0))
        weights = np.asarray(self.weights, dtype=np.float64)[way_idx]
        residential = np.asarray(self.residential, dtype=bool)[way_idx]
        return (seg_lon[keep], seg_lat[keep], (seg_len * weights)[keep],
                np.where(residential, seg_len, 0.0)[keep])


def main():
    pbf_path = find_pbf(BASE_DIR)
    worship_path = os.path.join(BASE_DIR, "places_of_worship_sa.geojson")
    output_path = os.path.join(BASE_DIR, "worship_gaps_sa.json")
    legacy_output_path = os.path.join(BASE_DIR, "worship_gaps_sa.geojson")

    # 1. Load Saudi boundary
    print("Loading Saudi Arabia boundary...")
    boundary_poly, boundary_prep, bounds = load_boundary(BASE_DIR)

    # 2. Load already extracted places of worship
    print("Loading existing places of worship...")
    try:
        with open(worship_path, "r", encoding="utf-8") as f:
            worship_data = json.load(f)
        worship_features = worship_data["features"]
    except Exception as e:
        print(f"Error loading places of worship: {e}")
        sys.exit(1)

    # 3. Extract weighted road length from PBF
    print("Scanning PBF for all drivable road networks...")
    start_time = time.time()
    extractor = DrivableRoadExtractor(boundary_prep, bounds)
    extractor.apply_file(pbf_path, locations=True, filters=[osmium.filter.KeyFilter("highway")])
    seg_lon, seg_lat, seg_weighted_m, seg_res_m = extractor.road_segments()
    print(f"Extracted {len(seg_lon)} road ways inside Saudi Arabia in {time.time() - start_time:.2f} seconds.")

    # 4. Map roads to a 2D coordinate grid
    # Grid size in degrees (~0.004 deg is approx 440 m, close to typical
    # neighborhood mosque spacing) so a cell no longer spans both
    # "next to a mosque" and "far from one".
    GRID_SIZE = 0.004
    MIN_ROADS_PER_CELL = 2
    MIN_GAP_DISTANCE_M = 750   # walkable distance; below this, not a gap
    MAX_GAP_SCORE_DISTANCE_M = 3000

    print("Indexing places of worship for nearest-distance queries...")
    worship_tree = STRtree([
        Point(f["geometry"]["coordinates"][0] * (111_320.0 * math.cos(math.radians(f["geometry"]["coordinates"][1]))),
              f["geometry"]["coordinates"][1] * M_PER_DEG_LAT)
        for f in worship_features
    ])

    print("Mapping roads to grid...")
    # Per-cell sums with numpy. np.bincount adds in input order, and cells are
    # visited in first-seen order, so results match a sequential dict loop.
    grid_x = (seg_lon / GRID_SIZE).astype(np.int64)  # truncates like int()
    grid_y = (seg_lat / GRID_SIZE).astype(np.int64)
    if len(grid_x):
        y_span = int(grid_y.max() - grid_y.min()) + 1
        cell_ids = (grid_x - grid_x.min()) * y_span + (grid_y - grid_y.min())
        _, first_seen, cell_of_seg = np.unique(cell_ids, return_index=True, return_inverse=True)
    else:
        first_seen = cell_of_seg = np.zeros(0, dtype=np.int64)
    n_cells = len(first_seen)
    cell_n = np.bincount(cell_of_seg, minlength=n_cells)
    cell_road_m = np.bincount(cell_of_seg, weights=seg_weighted_m, minlength=n_cells)
    cell_res_m = np.bincount(cell_of_seg, weights=seg_res_m, minlength=n_cells)
    cell_sum_lon = np.bincount(cell_of_seg, weights=seg_lon, minlength=n_cells)
    cell_sum_lat = np.bincount(cell_of_seg, weights=seg_lat, minlength=n_cells)

    # 5. Identify coverage gaps by actual distance to the nearest place of worship
    print("Computing coverage gaps and AI urgency scores...")
    candidate_keys = []
    candidate_points = []      # (lon, lat) in degrees, for output/containment
    candidate_points_m = []    # projected meters, for nearest-distance query
    candidate_lengths = []
    candidate_res_lengths = []

    for c in np.argsort(first_seen, kind="stable"):
        n = int(cell_n[c])
        if n < MIN_ROADS_PER_CELL:
            continue

        rep_lon = float(cell_sum_lon[c]) / n
        rep_lat = float(cell_sum_lat[c]) / n

        seg = first_seen[c]
        candidate_keys.append((int(grid_x[seg]), int(grid_y[seg])))
        candidate_points.append((rep_lon, rep_lat))
        candidate_points_m.append((rep_lon * (111_320.0 * math.cos(math.radians(rep_lat))), rep_lat * M_PER_DEG_LAT))
        candidate_lengths.append(float(cell_road_m[c]))
        candidate_res_lengths.append(float(cell_res_m[c]))

    gap_cells = []
    if candidate_points_m:
        xy_m = np.asarray(candidate_points_m)
        _, distances = worship_tree.query_nearest(
            shapely.points(xy_m[:, 0], xy_m[:, 1]), return_distance=True, all_matches=False
        )

        # Vectorized point-in-boundary test (same predicate as prepared contains).
        lonlat = np.asarray(candidate_points)
        shapely.prepare(boundary_poly)
        inside_mask = shapely.contains_xy(boundary_poly, lonlat[:, 0], lonlat[:, 1])

        for i, key in enumerate(candidate_keys):
            if not inside_mask[i]:
                continue

            distance_m = distances[i]
            if distance_m < MIN_GAP_DISTANCE_M:
                continue  # close enough to a mosque -> not a gap

            road_length_m = candidate_lengths[i]
            res_length_m = candidate_res_lengths[i]

            # Gap intensity blends road-length density (as before, but now
            # scale-invariant to OSM way-splitting) with how far the nearest
            # mosque actually is.
            distance_factor = min(distance_m, MAX_GAP_SCORE_DISTANCE_M) / MIN_GAP_DISTANCE_M
            gap_score = (1.0 + math.log(max(road_length_m, 1.0))) * distance_factor

            # Residential Urgency Score (0 to 100):
            # Prioritizes inhabited neighborhoods (high residential road length) far from mosques,
            # while down-ranking isolated highway interchanges or uninhabited desert tracts.
            res_ratio = res_length_m / max(road_length_m, 1.0)
            if res_length_m > 0:
                raw_urgency = math.log1p(res_length_m) * (1.0 + res_ratio) * distance_factor * 4.5
                urgency_score = min(100.0, max(1.0, round(raw_urgency, 1)))
            else:
                urgency_score = min(25.0, round(gap_score * 0.4, 1))

            gap_cells.append([
                key[0], key[1],
                round(road_length_m),
                round(gap_score, 3),
                urgency_score
            ])

    print(f"Detected {len(gap_cells)} coverage gap areas across Saudi Arabia.")

    # 6. Save gaps as a compact grid. A cell's position is implied by its grid
    # index (cell (gx, gy) spans [gx*grid_size, (gx+1)*grid_size) in lon/lat).
    write_json(output_path, {
        "grid_size": GRID_SIZE,
        "fields": ["gx", "gy", "road_length_m", "gap_score", "urgency_score"],
        "cells": gap_cells,
    })
    if os.path.exists(legacy_output_path):
        os.remove(legacy_output_path)
    update_summary("gaps", {"count": len(gap_cells)}, pbf_path)

    print(f"Coverage gaps written to {output_path}")


if __name__ == "__main__":
    main()
