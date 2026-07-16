import glob
import os
import osmium
import json
import sys
import time
import math
from shapely.geometry import shape, Point, Polygon
from shapely.prepared import prep

# Resolve all paths relative to this script so it runs on any machine.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Equirectangular scaling around KSA's ~24 deg N latitude, sufficient for
# local area calculations (not a true projection). Duplicated from
# calculate_gaps.py on purpose: this script is meant to run on its own
# schedule (e.g. weekly) independent of the daily extract_places.py /
# calculate_gaps.py pipeline, and must not import from or modify them.
REF_LAT_RAD = math.radians(24.0)
M_PER_DEG_LAT = 110_574.0
M_PER_DEG_LON = 111_320.0 * math.cos(REF_LAT_RAD)

# Heuristic thresholds, not derived from the data. Tune as needed.
MIN_REASONABLE_AREA_M2 = 20      # smaller than a small prayer room -> likely a mis-mapped footprint
MAX_REASONABLE_AREA_M2 = 15000   # bigger than almost all neighborhood/city mosques -> likely merged buildings or an oversized outline

def find_pbf(base_dir):
    matches = glob.glob(os.path.join(base_dir, "*.osm.pbf"))
    if not matches:
        sys.exit("No .osm.pbf file found in " + base_dir)
    if len(matches) > 1:
        sys.exit("Multiple .osm.pbf files found, expected exactly one: " + ", ".join(matches))
    return matches[0]

class MosqueSizeExtractor(osmium.SimpleHandler):
    def __init__(self, boundary_prep, bounds):
        super().__init__()
        self.boundary_prep = boundary_prep
        self.minx, self.miny, self.maxx, self.maxy = bounds
        self.sizes = {}

    def way(self, w):
        tags = w.tags
        if not tags:
            return
        amenity = tags.get('amenity')
        if not (amenity == 'place_of_worship' or amenity == 'mosque' or tags.get('building') == 'mosque'):
            return
        try:
            nodes = w.nodes
            n_nodes = len(nodes)
            if n_nodes < 4:
                return  # not a closed ring, can't compute an area

            sum_lat = sum(node.lat for node in nodes)
            sum_lon = sum(node.lon for node in nodes)
            centroid_lat = sum_lat / n_nodes
            centroid_lon = sum_lon / n_nodes
            if not (self.minx <= centroid_lon <= self.maxx and self.miny <= centroid_lat <= self.maxy):
                return
            if not self.boundary_prep.contains(Point(centroid_lon, centroid_lat)):
                return

            ring_m = [
                (node.lon * M_PER_DEG_LON, node.lat * M_PER_DEG_LAT)
                for node in nodes
            ]
            area_m2 = Polygon(ring_m).area
            if area_m2 <= 0:
                return

            if area_m2 < MIN_REASONABLE_AREA_M2:
                size_flag = "too_small"
            elif area_m2 > MAX_REASONABLE_AREA_M2:
                size_flag = "too_large"
            else:
                return  # within the reasonable range, not an outlier

            self.sizes[str(w.id)] = {
                "area_m2": round(area_m2, 1),
                "size_flag": size_flag
            }
        except osmium.InvalidLocationError:
            pass

def main():
    pbf_path = find_pbf(BASE_DIR)
    boundary_path = os.path.join(BASE_DIR, "sa_boundary.geojson")
    output_path = os.path.join(BASE_DIR, "mosque_sizes.json")

    print("Loading Saudi Arabia boundary...")
    try:
        with open(boundary_path, "r", encoding="utf-8") as f:
            boundary_data = json.load(f)
        boundary_poly = shape(boundary_data["geometry"])
    except Exception as e:
        print(f"Error loading boundary: {e}")
        sys.exit(1)

    boundary_prep = prep(boundary_poly)
    bounds = boundary_poly.bounds

    print("Scanning PBF for mosque building footprints inside Saudi Arabia...")
    start_time = time.time()

    extractor = MosqueSizeExtractor(boundary_prep, bounds)
    extractor.apply_file(pbf_path, locations=True)

    duration = time.time() - start_time
    print(f"Scan completed in {duration:.2f} seconds.")

    too_small = sum(1 for v in extractor.sizes.values() if v["size_flag"] == "too_small")
    too_large = sum(1 for v in extractor.sizes.values() if v["size_flag"] == "too_large")
    print(f"Found {len(extractor.sizes)} size outliers ({too_small} too small, {too_large} too large).")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(extractor.sizes, f, indent=2, ensure_ascii=False)

    print(f"Mosque size outliers written to {output_path}")

if __name__ == "__main__":
    main()
