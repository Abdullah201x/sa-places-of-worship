import os
import osmium
import json
import sys
import time
from shapely.geometry import shape, Point

# Resolve all paths relative to this script so it runs on any machine.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class PlacesOfWorshipExtractor(osmium.SimpleHandler):
    def __init__(self, boundary_poly):
        super().__init__()
        self.boundary_poly = boundary_poly
        self.features = []

    def node(self, n):
        if ('amenity' in n.tags and n.tags['amenity'] in ('place_of_worship', 'mosque')) or \
           ('building' in n.tags and n.tags['building'] == 'mosque'):
            # Check coordinates
            try:
                lon, lat = n.location.lon, n.location.lat
                pt = Point(lon, lat)
                if self.boundary_poly.contains(pt):
                    self.features.append(self._create_feature(n.id, lat, lon, n.tags, "Point", n))
            except osmium.InvalidLocationError:
                pass

    def way(self, w):
        if ('amenity' in w.tags and w.tags['amenity'] in ('place_of_worship', 'mosque')) or \
           ('building' in w.tags and w.tags['building'] == 'mosque'):
            # Calculate centroid
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
                        self.features.append(self._create_feature(w.id, centroid_lat, centroid_lon, w.tags, "Polygon", w))
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
    pbf_path = os.path.join(BASE_DIR, "gcc-states-260709-internal.osm.pbf")
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

    print("Scanning PBF and extracting places of worship inside Saudi Arabia...")
    start_time = time.time()
    
    extractor = PlacesOfWorshipExtractor(boundary_poly)
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
