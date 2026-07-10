import os
import osmium
import sys
import json
from shapely.geometry import LineString, mapping
from shapely.ops import polygonize, unary_union

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

def main():
    pbf_path = os.path.join(BASE_DIR, "gcc-states-260709-internal.osm.pbf")
    output_path = os.path.join(BASE_DIR, "sa_boundary.geojson")
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
