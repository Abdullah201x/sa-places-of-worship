import os
import osmium
import sys
import json
from shapely.geometry import LineString, mapping
from shapely.ops import polygonize, unary_union

from common import find_pbf

# Resolve all paths relative to this script so it runs on any machine.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class RelationWayCollector(osmium.SimpleHandler):
    def __init__(self, target_relation_id):
        super().__init__()
        self.target_relation_id = target_relation_id
        self.way_ids = set()

    def relation(self, r):
        if r.id == self.target_relation_id:
            for member in r.members:
                if member.type == 'w' and member.role == 'outer':
                    self.way_ids.add(member.ref)

class WayCoordinateCollector(osmium.SimpleHandler):
    def __init__(self, target_way_ids):
        super().__init__()
        self.target_way_ids = target_way_ids
        self.lines = []

    def way(self, w):
        if w.id in self.target_way_ids:
            coords = []
            try:
                for node in w.nodes:
                    coords.append((node.lon, node.lat))
                if len(coords) >= 2:
                    self.lines.append(LineString(coords))
            except osmium.InvalidLocationError:
                # Node location was not resolved, skip
                pass

import shutil

def check_cached_boundary(output_path, pbf_path):
    if "--force" not in sys.argv:
        pbf_mtime = os.path.getmtime(pbf_path) if os.path.exists(pbf_path) else 0
        if os.path.exists(output_path) and os.path.getmtime(output_path) >= pbf_mtime:
            print(f"[SKIP] sa_boundary.geojson already exists and is up to date.")
            return True

        sister_dirs = [
            os.path.abspath(os.path.join(BASE_DIR, "..", "GCC20260707")),
            os.path.abspath(os.path.join(BASE_DIR, "..", "random osm mapping")),
            os.path.abspath(os.path.join(BASE_DIR, "..", "street_lighting_SA")),
            r"C:\Users\abdul\Desktop\GCC20260707",
            r"C:\Users\abdul\Desktop\random osm mapping",
            r"C:\Users\abdul\Desktop\street_lighting_SA",
        ]
        for s_dir in sister_dirs:
            candidate = os.path.join(s_dir, "sa_boundary.geojson")
            if os.path.exists(candidate) and os.path.abspath(candidate) != os.path.abspath(output_path):
                if os.path.getmtime(candidate) >= pbf_mtime:
                    print(f"[COPY] Copying cached sa_boundary.geojson from {s_dir}...")
                    shutil.copy2(candidate, output_path)
                    return True
    return False

def main():
    pbf_path = find_pbf(BASE_DIR)
    output_path = os.path.join(BASE_DIR, "sa_boundary.geojson")
    if check_cached_boundary(output_path, pbf_path):
        return

    target_rel_id = 307584

    print("Pass 1: Identifying boundary ways...")
    collector = RelationWayCollector(target_rel_id)
    collector.apply_file(pbf_path)
    
    print(f"Found {len(collector.way_ids)} outer ways for Saudi Arabia boundary.")
    
    print("Pass 2: Extracting way coordinates...")
    coord_collector = WayCoordinateCollector(collector.way_ids)
    # Enable location caching so nodes in ways have coordinates
    coord_collector.apply_file(pbf_path, locations=True)
    
    print(f"Extracted {len(coord_collector.lines)} line segments.")
    
    print("Assembling polygon boundary...")
    # Merge line segments
    union_lines = unary_union(coord_collector.lines)
    # Polygonize the lines
    polygons = list(polygonize(union_lines))
    
    if not polygons:
        print("Error: Could not polygonize the line segments.")
        # If we can't polygonize (e.g. because of small gaps), let's just make a multi-linestring
        geo_json = {
            "type": "Feature",
            "properties": {"name": "Saudi Arabia (Outline Only)"},
            "geometry": mapping(union_lines)
        }
    else:
        # Merge all polygonized parts into one multipolygon/polygon
        final_poly = unary_union(polygons)
        geo_json = {
            "type": "Feature",
            "properties": {
                "name": "Saudi Arabia",
                "relation_id": target_rel_id
            },
            "geometry": mapping(final_poly)
        }
        
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(geo_json, f, indent=2)
        
    print(f"Saudi Arabia boundary written to {output_path}")

if __name__ == "__main__":
    main()
