import glob
import os
import osmium
import json
import sys
import time
from shapely.geometry import shape, Point
from shapely.prepared import prep

# Resolve all paths relative to this script so it runs on any machine.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def find_pbf(base_dir):
    matches = glob.glob(os.path.join(base_dir, "*.osm.pbf"))
    if not matches:
        sys.exit("No .osm.pbf file found in " + base_dir)
    if len(matches) > 1:
        sys.exit("Multiple .osm.pbf files found, expected exactly one: " + ", ".join(matches))
    return matches[0]

class PlacesOfWorshipExtractor(osmium.SimpleHandler):
    def __init__(self, boundary_prep, bounds):
        super().__init__()
        self.boundary_prep = boundary_prep
        self.minx, self.miny, self.maxx, self.maxy = bounds
        self.features = []

    def node(self, n):
        tags = n.tags
        if not tags:
            return
        amenity = tags.get('amenity')
        if amenity == 'place_of_worship' or amenity == 'mosque' or tags.get('building') == 'mosque':
            # Check coordinates
            try:
                lon, lat = n.location.lon, n.location.lat
                if self.minx <= lon <= self.maxx and self.miny <= lat <= self.maxy:
                    pt = Point(lon, lat)
                    if self.boundary_prep.contains(pt):
                        self.features.append(self._create_feature(n.id, lat, lon, tags, "Point", n))
            except osmium.InvalidLocationError:
                pass

    def way(self, w):
        tags = w.tags
        if not tags:
            return
        amenity = tags.get('amenity')
        if amenity == 'place_of_worship' or amenity == 'mosque' or tags.get('building') == 'mosque':
            # Calculate centroid
            try:
                nodes = w.nodes
                n_nodes = len(nodes)
                if n_nodes > 0:
                    sum_lat = sum(node.lat for node in nodes)
                    sum_lon = sum(node.lon for node in nodes)
                    centroid_lat = sum_lat / n_nodes
                    centroid_lon = sum_lon / n_nodes
                    if self.minx <= centroid_lon <= self.maxx and self.miny <= centroid_lat <= self.maxy:
                        pt = Point(centroid_lon, centroid_lat)
                        if self.boundary_prep.contains(pt):
                            self.features.append(self._create_feature(w.id, centroid_lat, centroid_lon, tags, "Polygon", w))
            except osmium.InvalidLocationError:
                pass

    def _create_feature(self, osm_id, lat, lon, tags, geom_type, osm_obj):
        religion = tags.get("religion", "unknown")
        if religion == "unknown":
            if tags.get("building") == "mosque" or tags.get("amenity") == "mosque":
                religion = "muslim"

        properties = {
            "osm_id": osm_id,
            "geom_type": geom_type,
            "name": tags.get("name", ""),
            "name_en": tags.get("name:en", ""),
            "name_original": tags.get("name", ""),
            "name_en_original": tags.get("name:en", ""),
            "religion": religion,
            "denomination": tags.get("denomination", "unknown"),
            "building": tags.get("building", ""),
            "amenity": tags.get("amenity", ""),
            "place_of_worship": tags.get("place_of_worship", ""),
            "wheelchair": tags.get("wheelchair", ""),
            "female": tags.get("female", tags.get("worship:female", tags.get("female_prayer_space", ""))),
            "capacity": tags.get("capacity", ""),
            "addr_city": tags.get("addr:city", ""),
            "last_edited_by": osm_obj.user,
            "user_id": osm_obj.uid,
            "changeset_id": osm_obj.changeset,
            "version": osm_obj.version,
            "edited_at": osm_obj.timestamp.isoformat()
        }
        
        # Capture any translation if name is empty
        if not properties["name"] and properties["name_en"]:
            properties["name"] = properties["name_en"]
        elif not properties["name_en"] and properties["name"]:
            properties["name_en"] = properties["name"]

        # Default fallback for naming
        if not properties["name"]:
            properties["name"] = "Mosque" if properties["religion"] == "muslim" else "Place of Worship"
            properties["name_en"] = "Mosque" if properties["religion"] == "muslim" else "Place of Worship"

        return {
            "type": "Feature",
            "properties": properties,
            "geometry": {
                "type": "Point",
                "coordinates": [lon, lat]
            }
        }

def main():
    pbf_path = find_pbf(BASE_DIR)
    boundary_path = os.path.join(BASE_DIR, "sa_boundary.geojson")
    output_path = os.path.join(BASE_DIR, "places_of_worship_sa.geojson")

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

    print("Scanning PBF and extracting places of worship inside Saudi Arabia...")
    start_time = time.time()
    
    extractor = PlacesOfWorshipExtractor(boundary_prep, bounds)
    extractor.apply_file(pbf_path, locations=True)
    
    duration = time.time() - start_time
    print(f"Extraction completed in {duration:.2f} seconds.")
    
    geojson_collection = {
        "type": "FeatureCollection",
        "features": extractor.features
    }
    
    print(f"Found {len(extractor.features)} places of worship inside Saudi Arabia boundaries.")
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(geojson_collection, f, indent=2, ensure_ascii=False)
        
    print(f"Places of worship written to {output_path}")

if __name__ == "__main__":
    main()
