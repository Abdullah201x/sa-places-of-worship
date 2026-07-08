import os
import osmium
import json
import sys
import time
import math
from shapely.geometry import shape, Point

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
    pbf_path = os.path.join(BASE_DIR, "gcc-states-260707.osm.pbf")
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

    # 4. Map both datasets to a 2D coordinate grid
    # Grid size in degrees (~0.02 deg is approx 2.2 km)
    GRID_SIZE = 0.02
    grid = {}

    print("Mapping places of worship to grid...")
    for f in worship_features:
        coords = f["geometry"]["coordinates"]
        lon, lat = coords[0], coords[1]
        
        grid_x = int(lon / GRID_SIZE)
        grid_y = int(lat / GRID_SIZE)
        key = (grid_x, grid_y)
        
        if key not in grid:
            grid[key] = {"res_count": 0, "worship_count": 0}
        grid[key]["worship_count"] += 1

    print("Mapping roads to grid...")
    for lon, lat in extractor.points:
        grid_x = int(lon / GRID_SIZE)
        grid_y = int(lat / GRID_SIZE)
        key = (grid_x, grid_y)
        
        if key not in grid:
            grid[key] = {"res_count": 0, "worship_count": 0}
        grid[key]["res_count"] += 1

    # 5. Identify coverage gaps (road count > 0 and worship count == 0)
    print("Computing coverage gaps...")
    gap_features = []
    
    for key, counts in grid.items():
        res_count = counts["res_count"]
        worship_count = counts["worship_count"]
        
        # A gap is defined as an inhabited cell with zero places of worship
        # Minimum threshold of 2 road segments to ensure it represents actual infrastructure
        if res_count >= 2 and worship_count == 0:
            grid_x, grid_y = key
            # Cell center coordinates
            cell_lon = (grid_x + 0.5) * GRID_SIZE
            cell_lat = (grid_y + 0.5) * GRID_SIZE
            
            # Verify cell center is inside Saudi Arabia
            cell_pt = Point(cell_lon, cell_lat)
            if boundary_poly.contains(cell_pt):
                # Calculate gap intensity score based on log of road density
                gap_score = 1.0 + math.log(res_count)
                
                gap_features.append({
                    "type": "Feature",
                    "properties": {
                        "grid_id": f"{grid_x}_{grid_y}",
                        "roads_count": res_count,
                        "gap_score": round(gap_score, 3)
                    },
                    "geometry": {
                        "type": "Point",
                        "coordinates": [cell_lon, cell_lat]
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
