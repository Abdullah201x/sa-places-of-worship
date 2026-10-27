import json
import math
import os
import sys
import time

import osmium
from shapely.geometry import Point
from shapely.strtree import STRtree

from common import (BASE_DIR, M_PER_DEG_LAT, M_PER_DEG_LON, find_pbf, load_boundary,
                    update_summary, write_json)

# Through-traffic road classes are downweighted: OSM fragments them into many
# short tagged segments (speed/lane/name changes), which inflates apparent
# density in cities without indicating where people actually live.
HIGHWAY_WEIGHTS = {
    'motorway': 0.2,
    'motorway_link': 0.2,
    'trunk': 0.2,
    'trunk_link': 0.2,
    'primary': 0.3,
    'primary_link': 0.3,
}
DEFAULT_HIGHWAY_WEIGHT = 1.0

class DrivableRoadExtractor(osmium.SimpleHandler):
    def __init__(self, boundary_prep, bounds):
        super().__init__()
        self.boundary_prep = boundary_prep
        self.minx, self.miny, self.maxx, self.maxy = bounds
        # (centroid_lon, centroid_lat, highway-weighted length in meters)
        self.roads = []

    def way(self, w):
        tags = w.tags
        if 'highway' in tags:
            h_type = tags['highway']
            # Exclude non-drivable pedestrian, construction, and service paths
            if h_type not in (
                'footway', 'path', 'steps', 'cycleway', 'pedestrian',
                'bridleway', 'corridor', 'platform', 'elevator',
                'proposed', 'construction', 'abandoned', 'escape', 'sidewalk'
            ):
                try:
                    # Single traversal coordinate retrieval to avoid repeated C++ wrapper overhead
                    coords = [(node.lon, node.lat) for node in w.nodes]
                    n_nodes = len(coords)
                    if n_nodes >= 2:
                        sum_lon = 0.0
                        sum_lat = 0.0
                        for lon, lat in coords:
                            sum_lon += lon
                            sum_lat += lat
                        centroid_lon = sum_lon / n_nodes
                        centroid_lat = sum_lat / n_nodes

                        if self.minx <= centroid_lon <= self.maxx and self.miny <= centroid_lat <= self.maxy:
                            pt = Point(centroid_lon, centroid_lat)
                            if self.boundary_prep.contains(pt):
                                length_m = 0.0
                                for i in range(n_nodes - 1):
                                    dx = (coords[i+1][0] - coords[i][0]) * M_PER_DEG_LON
                                    dy = (coords[i+1][1] - coords[i][1]) * M_PER_DEG_LAT
                                    length_m += math.hypot(dx, dy)
                                weight = HIGHWAY_WEIGHTS.get(h_type, DEFAULT_HIGHWAY_WEIGHT)
                                self.roads.append((centroid_lon, centroid_lat, length_m * weight))
                except osmium.InvalidLocationError:
                    pass

def main():
    pbf_path = find_pbf(BASE_DIR)
    worship_path = os.path.join(BASE_DIR, "places_of_worship_sa.geojson")
    output_path = os.path.join(BASE_DIR, "worship_gaps_sa.json")
    legacy_output_path = os.path.join(BASE_DIR, "worship_gaps_sa.geojson")

    # 1. Load Saudi boundary
    print("Loading Saudi Arabia boundary...")
    _, boundary_prep, bounds = load_boundary(BASE_DIR)

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
    extractor.apply_file(pbf_path, locations=True)
    print(f"Extracted {len(extractor.roads)} road ways inside Saudi Arabia in {time.time() - start_time:.2f} seconds.")

    # 4. Map roads to a 2D coordinate grid
    # Grid size in degrees (~0.004 deg is approx 440 m, close to typical
    # neighborhood mosque spacing) so a cell no longer spans both
    # "next to a mosque" and "far from one".
    GRID_SIZE = 0.004
    # Candidacy still requires >=2 distinct ways in a cell (not just one road
    # passing through empty land) - this stays a *way count*, unaffected by
    # the length-based scoring change below, so rural/desert candidacy is
    # unchanged from before. Weighted road length is only used afterwards, to
    # score *how* underserved a candidate cell is without being inflated by
    # OSM way-splitting (tag changes fragment ways into many short segments,
    # especially in cities).
    MIN_ROADS_PER_CELL = 2
    MIN_GAP_DISTANCE_M = 750   # walkable distance; below this, not a gap
    MAX_GAP_SCORE_DISTANCE_M = 3000

    print("Indexing places of worship for nearest-distance queries...")
    worship_tree = STRtree([
        Point(f["geometry"]["coordinates"][0] * M_PER_DEG_LON,
              f["geometry"]["coordinates"][1] * M_PER_DEG_LAT)
        for f in worship_features
    ])

    print("Mapping roads to grid...")
    grid = {}
    for lon, lat, weighted_length_m in extractor.roads:
        grid_x = int(lon / GRID_SIZE)
        grid_y = int(lat / GRID_SIZE)
        key = (grid_x, grid_y)

        if key in grid:
            cell = grid[key]
            cell["road_length_m"] += weighted_length_m
            cell["sum_lon"] += lon
            cell["sum_lat"] += lat
            cell["n"] += 1
        else:
            grid[key] = {
                "road_length_m": weighted_length_m,
                "sum_lon": lon,
                "sum_lat": lat,
                "n": 1
            }

    # 5. Identify coverage gaps by actual distance to the nearest place of worship
    print("Computing coverage gaps...")
    candidate_keys = []
    candidate_points = []      # (lon, lat) in degrees, for output/containment
    candidate_points_m = []    # projected meters, for nearest-distance query
    candidate_lengths = []

    for key, cell in grid.items():
        if cell["n"] < MIN_ROADS_PER_CELL:
            continue

        rep_lon = cell["sum_lon"] / cell["n"]
        rep_lat = cell["sum_lat"] / cell["n"]

        candidate_keys.append(key)
        candidate_points.append((rep_lon, rep_lat))
        candidate_points_m.append(Point(rep_lon * M_PER_DEG_LON, rep_lat * M_PER_DEG_LAT))
        candidate_lengths.append(cell["road_length_m"])

    gap_cells = []
    if candidate_points_m:
        _, distances = worship_tree.query_nearest(
            candidate_points_m, return_distance=True, all_matches=False
        )

        minx, miny, maxx, maxy = bounds
        inside_mask = [
            minx <= lo <= maxx and miny <= la <= maxy and boundary_prep.contains(Point(lo, la))
            for lo, la in candidate_points
        ]

        for i, key in enumerate(candidate_keys):
            if not inside_mask[i]:
                continue

            distance_m = distances[i]
            if distance_m < MIN_GAP_DISTANCE_M:
                continue  # close enough to a mosque -> not a gap

            road_length_m = candidate_lengths[i]

            # Gap intensity blends road-length density (as before, but now
            # scale-invariant to OSM way-splitting) with how far the nearest
            # mosque actually is, so a gap right next to a mosque in the same
            # coarse area no longer masks a genuinely underserved spot.
            distance_factor = min(distance_m, MAX_GAP_SCORE_DISTANCE_M) / MIN_GAP_DISTANCE_M
            gap_score = (1.0 + math.log(max(road_length_m, 1.0))) * distance_factor

            gap_cells.append([key[0], key[1], round(road_length_m), round(gap_score, 3)])

    print(f"Detected {len(gap_cells)} coverage gap areas across Saudi Arabia.")

    # 6. Save gaps as a compact grid. A cell's position is implied by its grid
    # index (cell (gx, gy) spans [gx*grid_size, (gx+1)*grid_size) in lon/lat),
    # so there's no need for a GeoJSON point per cell.
    write_json(output_path, {
        "grid_size": GRID_SIZE,
        "fields": ["gx", "gy", "road_length_m", "gap_score"],
        "cells": gap_cells,
    })
    if os.path.exists(legacy_output_path):
        os.remove(legacy_output_path)
    update_summary("gaps", {"count": len(gap_cells)}, pbf_path)

    print(f"Coverage gaps written to {output_path}")

if __name__ == "__main__":
    main()
