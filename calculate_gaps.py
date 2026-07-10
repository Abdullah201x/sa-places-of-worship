import os
import osmium
import json
import sys
import time
import math
import shapely
from shapely.geometry import shape, Point
from shapely.strtree import STRtree

# Resolve all paths relative to this script so it runs on any machine.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class DrivableRoadExtractor(osmium.SimpleHandler):
    def __init__(self, boundary_poly):
        super().__init__()
        self.boundary_poly = boundary_poly
        self.points = []

    def way(self, w):
        if 'highway' in w.tags:
            h_type = w.tags['highway']
            # Exclude non-drivable pedestrian, construction, and service paths
            if h_type not in (
                'footway', 'path', 'steps', 'cycleway', 'pedestrian', 
                'bridleway', 'corridor', 'platform', 'elevator', 
                'proposed', 'construction', 'abandoned', 'escape', 'sidewalk'
            ):
                try:
                    lats = []
                    lons = []
                    for node in w.nodes:
                        lats.append(node.lat)
                        lons.append(node.lon)
                    
                    if lats and lons:
                        centroid_lat = sum(lats) / len(lats)
                        centroid_lon = sum(lons) / len(lons)
                        pt = Point(centroid_lon, centroid_lat)
                        if self.boundary_poly.contains(pt):
                            self.points.append((centroid_lon, centroid_lat))
                except osmium.InvalidLocationError:
                    pass

def main():
    pbf_path = os.path.join(BASE_DIR, "gcc-states-260709-internal.osm.pbf")
    boundary_path = os.path.join(BASE_DIR, "sa_boundary.geojson")
    worship_path = os.path.join(BASE_DIR, "places_of_worship_sa.geojson")
    output_path = os.path.join(BASE_DIR, "worship_gaps_sa.geojson")

    # 1. Load Saudi boundary
    print("Loading Saudi Arabia boundary...")
    try:
        with open(boundary_path, "r", encoding="utf-8") as f:
            boundary_data = json.load(f)
        boundary_poly = shape(boundary_data["geometry"])
    except Exception as e:
        print(f"Error loading boundary: {e}")
        sys.exit(1)

    # 2. Load already extracted places of worship
    print("Loading existing places of worship...")
    try:
        with open(worship_path, "r", encoding="utf-8") as f:
            worship_data = json.load(f)
        worship_features = worship_data["features"]
    except Exception as e:
        print(f"Error loading places of worship: {e}")
        sys.exit(1)

    # 3. Extract road centroids from PBF
    print("Scanning PBF for all drivable road networks...")
    start_time = time.time()
    extractor = DrivableRoadExtractor(boundary_poly)
    extractor.apply_file(pbf_path, locations=True)
    print(f"Extracted {len(extractor.points)} road segments inside Saudi Arabia in {time.time() - start_time:.2f} seconds.")

    # 4. Map roads to a 2D coordinate grid
    # Grid size in degrees (~0.004 deg is approx 440 m, close to typical
    # neighborhood mosque spacing) so a cell no longer spans both
    # "next to a mosque" and "far from one".
    GRID_SIZE = 0.004
    MIN_ROADS_PER_CELL = 2
    MIN_GAP_DISTANCE_M = 750   # walkable distance; below this, not a gap
    MAX_GAP_SCORE_DISTANCE_M = 3000

    # Equirectangular scaling around KSA's ~24 deg N latitude, sufficient for
    # local nearest-neighbor distance (not a true projection).
    REF_LAT_RAD = math.radians(24.0)
    M_PER_DEG_LAT = 110_574.0
    M_PER_DEG_LON = 111_320.0 * math.cos(REF_LAT_RAD)

    print("Indexing places of worship for nearest-distance queries...")
    worship_tree = STRtree([
        Point(f["geometry"]["coordinates"][0] * M_PER_DEG_LON,
              f["geometry"]["coordinates"][1] * M_PER_DEG_LAT)
        for f in worship_features
    ])

    print("Mapping roads to grid...")
    grid = {}
    for lon, lat in extractor.points:
        grid_x = int(lon / GRID_SIZE)
        grid_y = int(lat / GRID_SIZE)
        key = (grid_x, grid_y)

        cell = grid.setdefault(key, {"res_count": 0, "sum_lon": 0.0, "sum_lat": 0.0})
        cell["res_count"] += 1
        cell["sum_lon"] += lon
        cell["sum_lat"] += lat

    # 5. Identify coverage gaps by actual distance to the nearest place of worship
    print("Computing coverage gaps...")
    candidate_keys = []
    candidate_points = []      # (lon, lat) in degrees, for output/containment
    candidate_points_m = []    # projected meters, for nearest-distance query
    candidate_res = []

    for key, cell in grid.items():
        res_count = cell["res_count"]
        if res_count < MIN_ROADS_PER_CELL:
            continue

        rep_lon = cell["sum_lon"] / res_count
        rep_lat = cell["sum_lat"] / res_count

        candidate_keys.append(key)
        candidate_points.append((rep_lon, rep_lat))
        candidate_points_m.append(Point(rep_lon * M_PER_DEG_LON, rep_lat * M_PER_DEG_LAT))
        candidate_res.append(res_count)

    gap_features = []
    if candidate_points_m:
        shapely.prepare(boundary_poly)
        _, distances = worship_tree.query_nearest(
            candidate_points_m, return_distance=True, all_matches=False
        )
        inside_mask = shapely.contains(
            boundary_poly, [Point(lo, la) for lo, la in candidate_points]
        )

        for i, key in enumerate(candidate_keys):
            if not inside_mask[i]:
                continue

            distance_m = distances[i]
            if distance_m < MIN_GAP_DISTANCE_M:
                continue  # close enough to a mosque -> not a gap

            res_count = candidate_res[i]
            rep_lon, rep_lat = candidate_points[i]

            # Gap intensity blends road density (as before) with how far the
            # nearest mosque actually is, so a gap right next to a mosque in
            # the same coarse area no longer masks a genuinely underserved spot.
            distance_factor = min(distance_m, MAX_GAP_SCORE_DISTANCE_M) / MIN_GAP_DISTANCE_M
            gap_score = (1.0 + math.log(res_count)) * distance_factor

            gap_features.append({
                "type": "Feature",
                "properties": {
                    "grid_id": f"{key[0]}_{key[1]}",
                    "roads_count": res_count,
                    "gap_score": round(gap_score, 3)
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [round(rep_lon, 6), round(rep_lat, 6)]
                }
            })

    print(f"Detected {len(gap_features)} coverage gap areas across Saudi Arabia.")

    # 6. Save gaps to GeoJSON
    geojson_collection = {
        "type": "FeatureCollection",
        "features": gap_features
    }
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(geojson_collection, f, indent=2, ensure_ascii=False)
        
    print(f"Coverage gaps written to {output_path}")

if __name__ == "__main__":
    main()
