#!/usr/bin/env python3
"""
Extracts the 13 administrative provinces of Saudi Arabia (admin_level=4)
from the OSM PBF extract into sa_regions.geojson.

Output FeatureCollection features:
  - id: ISO 3166-2 code (e.g. "SA-01")
  - properties: { osm_id, code, name, name_en }
  - geometry: Polygon or MultiPolygon
"""

import os
import sys
import osmium
from shapely.geometry import LineString, mapping
from shapely.ops import polygonize, unary_union

from common import BASE_DIR, configure_utf8_output, find_pbf, update_summary, write_json

configure_utf8_output()


class RegionRelationCollector(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.regions = {}  # rel_id -> metadata dict
        self.all_way_ids = set()

    def relation(self, r):
        iso = r.tags.get("ISO3166-2", "")
        if (r.tags.get("boundary") == "administrative"
                and r.tags.get("admin_level") == "4"
                and iso.startswith("SA-")):
            outer_ways = set()
            for m in r.members:
                if m.type == "w" and m.role == "outer":
                    outer_ways.add(m.ref)
                    self.all_way_ids.add(m.ref)

            self.regions[r.id] = {
                "osm_id": r.id,
                "code": iso,
                "name": r.tags.get("name", ""),
                "name_en": r.tags.get("name:en", ""),
                "ways": outer_ways,
            }


class RegionWayCollector(osmium.SimpleHandler):
    def __init__(self, target_ways):
        super().__init__()
        self.target_ways = target_ways
        self.way_lines = {}

    def way(self, w):
        if w.id in self.target_ways:
            coords = []
            try:
                for node in w.nodes:
                    coords.append((node.lon, node.lat))
                if len(coords) >= 2:
                    self.way_lines[w.id] = LineString(coords)
            except osmium.InvalidLocationError:
                pass


def check_cached_regions(output_path, pbf_path):
    if "--force" not in sys.argv:
        pbf_mtime = os.path.getmtime(pbf_path) if os.path.exists(pbf_path) else 0
        if os.path.exists(output_path) and os.path.getmtime(output_path) >= pbf_mtime:
            print("[SKIP] sa_regions.geojson already exists and is up to date.")
            return True
    return False


def main():
    pbf_path = find_pbf(BASE_DIR)
    output_path = os.path.join(BASE_DIR, "sa_regions.geojson")

    if check_cached_regions(output_path, pbf_path):
        return

    print("Pass 1: Identifying administrative region relations...")
    rel_collector = RegionRelationCollector()
    rel_collector.apply_file(pbf_path)
    print(f"Found {len(rel_collector.regions)} Saudi provinces with {len(rel_collector.all_way_ids)} outer ways.")

    print("Pass 2: Extracting way coordinates...")
    way_collector = RegionWayCollector(rel_collector.all_way_ids)
    way_collector.apply_file(pbf_path, locations=True)
    print(f"Resolved {len(way_collector.way_lines)} / {len(rel_collector.all_way_ids)} outer ways.")

    features = []
    for rel_id, info in sorted(rel_collector.regions.items(), key=lambda x: x[1]["code"]):
        lines = [way_collector.way_lines[wid] for wid in info["ways"] if wid in way_collector.way_lines]
        if not lines:
            print(f"  [WARN] No lines found for {info['code']} ({info['name']})")
            continue

        union_lines = unary_union(lines)
        polys = list(polygonize(union_lines))
        if not polys:
            print(f"  [WARN] Could not polygonize {info['code']} ({info['name']})")
            continue

        geom = unary_union(polys)
        if not geom.is_valid:
            geom = geom.buffer(0)

        feature = {
            "type": "Feature",
            "id": info["code"],
            "properties": {
                "osm_id": info["osm_id"],
                "code": info["code"],
                "name": info["name"],
                "name_en": info["name_en"],
            },
            "geometry": mapping(geom),
        }
        features.append(feature)
        print(f"  [OK] {info['code']}: {info['name']} ({info['name_en']}) -> {geom.geom_type}")

    feature_collection = {
        "type": "FeatureCollection",
        "features": features,
    }

    write_json(output_path, feature_collection)
    update_summary("regions", {"count": len(features)}, pbf_path=pbf_path)
    print(f"\nSaved {len(features)} provinces to {output_path}")


if __name__ == "__main__":
    main()
