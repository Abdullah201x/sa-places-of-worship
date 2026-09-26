"""
detect_geometry_anomalies.py
============================
Machine Learning (Unsupervised) Spatial Anomaly Detection for Mosques in Saudi Arabia.

How it works:
1. Extract geometric features from OSM mosque building footprints using Shapely.
2. Train an Isolation Forest (scikit-learn) to learn what "normal" mosques look like.
3. Flag shapes that deviate drastically (spaghetti shapes, distorted outlines, excessive vertices, oversized blocks).
4. Output a ranked list of suspicious mosques with direct OpenStreetMap links for verification and fixing.
"""

import os
import sys
import glob
import json
import math
import time

# Ensure UTF-8 output in Windows terminal for Arabic characters
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import osmium
from shapely.geometry import shape, Point, Polygon
from shapely.prepared import prep
import numpy as np
from sklearn.ensemble import IsolationForest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Equirectangular scaling around KSA's ~24 deg N latitude for fast local metric calculations
REF_LAT_RAD = math.radians(24.0)
M_PER_DEG_LAT = 110_574.0
M_PER_DEG_LON = 111_320.0 * math.cos(REF_LAT_RAD)


def find_pbf(base_dir=None):
    if base_dir is None:
        base_dir = BASE_DIR
    search_dirs = [
        base_dir,
        os.path.abspath(os.path.join(base_dir, "..", "update osm")),
        r"C:\Users\abdul\Desktop\update osm",
    ]
    for d in search_dirs:
        if os.path.exists(d):
            matches = glob.glob(os.path.join(d, "*.osm.pbf")) + glob.glob(os.path.join(d, "*.pbf"))
            seen = set()
            unique = [m for m in matches if not (m in seen or seen.add(m))]
            if unique:
                return unique[0]
    sys.exit("No .osm.pbf or .pbf file found.")


class MosqueFeatureExtractor(osmium.SimpleHandler):
    """
    Extracts geometric features from every mosque building footprint inside KSA.
    """
    def __init__(self, boundary_prep, bounds):
        super().__init__()
        self.boundary_prep = boundary_prep
        self.minx, self.miny, self.maxx, self.maxy = bounds
        self.records = []

    def way(self, w):
        tags = w.tags
        if not tags:
            return
        if tags.get('place_of_worship') == 'musalla':
            return  # Musallas are legitimately huge open-air prayer grounds

        amenity = tags.get('amenity')
        building = tags.get('building')
        if not (amenity in ('place_of_worship', 'mosque') or building == 'mosque'):
            return

        try:
            nodes = w.nodes
            n_nodes = len(nodes)
            if n_nodes < 4:
                return

            sum_lat = sum(n.lat for n in nodes)
            sum_lon = sum(n.lon for n in nodes)
            centroid_lat = sum_lat / n_nodes
            centroid_lon = sum_lon / n_nodes

            # Boundary filter
            if not (self.minx <= centroid_lon <= self.maxx and self.miny <= centroid_lat <= self.maxy):
                return
            if not self.boundary_prep.contains(Point(centroid_lon, centroid_lat)):
                return

            # Projected coordinates in meters
            ring_m = [(n.lon * M_PER_DEG_LON, n.lat * M_PER_DEG_LAT) for n in nodes]
            poly = Polygon(ring_m)
            area_m2 = poly.area
            perimeter_m = poly.length

            if area_m2 <= 0 or perimeter_m <= 0:
                return

            # FEATURE 1: Area (m2)
            # FEATURE 2: Perimeter (m)
            # FEATURE 3: Polsby-Popper Compactness (4 * pi * Area / Perimeter^2)
            #   - Neat circle = 1.0, square = ~0.78, elongated/irregular shapes < 0.3
            compactness = (4.0 * math.pi * area_m2) / (perimeter_m ** 2)

            # FEATURE 4: Node Count (vertex complexity)
            # FEATURE 5: Area per Node (ratio)
            area_per_node = area_m2 / n_nodes

            name = tags.get('name', tags.get('name:ar', tags.get('name:en', 'Unnamed Mosque')))

            self.records.append({
                "osm_id": w.id,
                "name": name,
                "centroid": (round(centroid_lat, 6), round(centroid_lon, 6)),
                "area_m2": round(area_m2, 1),
                "perimeter_m": round(perimeter_m, 1),
                "compactness": round(compactness, 4),
                "node_count": n_nodes,
                "area_per_node": round(area_per_node, 1),
            })
        except osmium.InvalidLocationError:
            pass


def train_anomaly_detector(records, contamination=0.015):
    """
    Trains an Isolation Forest model to detect spatial outliers.
    
    contamination: Estimated fraction of outliers in the dataset (~1.5%).
    """
    print(f"\n[ML Step 1/3] Preparing feature matrix for {len(records):,} mosques...")

    # Build the 2D feature array X for scikit-learn
    # We use log-transforms on area and perimeter because building sizes span multiple orders of magnitude
    feature_matrix = []
    for r in records:
        feature_vector = [
            math.log10(max(r["area_m2"], 1.0)),          # Log Area
            math.log10(max(r["perimeter_m"], 1.0)),      # Log Perimeter
            r["compactness"],                             # Compactness (0 to 1)
            math.log10(max(r["node_count"], 1.0)),       # Log Node Count
            math.log10(max(r["area_per_node"], 0.1)),    # Log Area/Node
        ]
        feature_matrix.append(feature_vector)

    X = np.array(feature_matrix)

    print("[ML Step 2/3] Training Isolation Forest model...")
    # IsolationForest isolates observations by randomly selecting a feature and splitting value.
    # Outliers require far fewer splits to isolate than normal points.
    model = IsolationForest(
        n_estimators=150,           # Number of decision trees
        contamination=contamination, # Proportion of anomalies to flag
        random_state=42,            # For reproducible results
        n_jobs=-1                   # Use all CPU cores
    )
    model.fit(X)

    print("[ML Step 3/3] Scoring geometries and ranking anomalies...")
    # decision_function gives a continuous anomaly score:
    # Lower / more negative -> stronger anomaly
    # Higher / positive -> normal shape
    raw_scores = model.decision_function(X)
    predictions = model.predict(X)  # -1 for anomaly, 1 for normal

    for i, r in enumerate(records):
        r["anomaly_score"] = round(float(raw_scores[i]), 4)
        r["is_anomaly"] = bool(predictions[i] == -1)

    # Sort so the most severe anomalies appear first
    anomalies = [r for r in records if r["is_anomaly"]]
    anomalies.sort(key=lambda x: x["anomaly_score"])

    return anomalies, records


def diagnose_anomaly(r):
    """Provides a human-readable explanation of why this mosque was flagged."""
    reasons = []
    if r["node_count"] > 100:
        reasons.append(f"عدد عقد مفرط جداً ({r['node_count']} عقدة — رسم تفصيلي معقد أو استيراد CAD)")
    elif r["node_count"] > 40 and r["area_m2"] < 1500:
        reasons.append(f"كثافة عقد عالية بالنسبة للمساحة ({r['node_count']} عقدة لمساحة {r['area_m2']} م²)")

    if r["compactness"] < 0.35:
        reasons.append(f"شكل غير متناسق أو مفرط الاستطالة (Compactness={r['compactness']:.2f})")
    elif r["compactness"] < 0.45 and r["node_count"] > 25:
        reasons.append(f"محيط متعرج كثير الانكسارات (Compactness={r['compactness']:.2f})")

    if r["area_m2"] < 25:
        reasons.append(f"مساحة متناهية الصغر ({r['area_m2']} م²)")
    elif r["area_m2"] > 15000:
        reasons.append(f"مساحة استثنائية الضخامة ({r['area_m2']:,} م²)")

    if not reasons:
        reasons.append("انحراف مركب في تناسق النسبة بين المساحة والمحيط والعقد")
    return " • ".join(reasons)


def main():
    pbf_path = find_pbf(BASE_DIR)
    boundary_path = os.path.join(BASE_DIR, "sa_boundary.geojson")
    output_path = os.path.join(BASE_DIR, "mosque_anomalies.json")

    print("=" * 65)
    print("  MOSQUE GEOMETRY ANOMALY DETECTION (ISOLATION FOREST - ML)")
    print("=" * 65)
    print(f"OSM PBF Source: {pbf_path}")

    # Load Saudi Arabia boundary polygon
    with open(boundary_path, "r", encoding="utf-8") as f:
        boundary_data = json.load(f)
    boundary_poly = shape(boundary_data["geometry"])
    boundary_prep = prep(boundary_poly)

    # Extract geometries
    print("\nScanning building footprints inside Saudi Arabia...")
    t0 = time.time()
    extractor = MosqueFeatureExtractor(boundary_prep, boundary_poly.bounds)
    extractor.apply_file(pbf_path, locations=True)
    t_extract = time.time() - t0
    print(f"Extracted features for {len(extractor.records):,} mosque footprints in {t_extract:.1f}s.")

    # Run Machine Learning Model
    anomalies, all_scored = train_anomaly_detector(extractor.records, contamination=0.015)

    print(f"\nModel identified {len(anomalies)} anomalous mosque geometries (~1.5% of total).")
    print("=" * 65)
    print("TOP 10 MOST SEVERE ANOMALIES DETECTED:")
    print("=" * 65)

    for rank, a in enumerate(anomalies[:10], 1):
        reason = diagnose_anomaly(a)
        lat, lon = a["centroid"]
        osm_url = f"https://www.openstreetmap.org/way/{a['osm_id']}"
        josm_url = f"http://127.0.0.1:8111/load_and_zoom?left={lon-0.001}&right={lon+0.001}&top={lat+0.001}&bottom={lat-0.001}&select=way{a['osm_id']}"
        
        print(f"\n#{rank} [{a['name']}] (OSM Way ID: {a['osm_id']})")
        print(f"   • Anomaly Score: {a['anomaly_score']} (Lower = more abnormal)")
        print(f"   • Area: {a['area_m2']:,} m² | Perimeter: {a['perimeter_m']:,} m | Nodes: {a['node_count']} | Compactness: {a['compactness']}")
        print(f"   • Diagnosis: {reason}")
        print(f"   • OSM Link: {osm_url}")

    # Save to JSON
    # Map by osm_id so it can be merged directly into the dashboard
    anomalies_dict = {
        str(a["osm_id"]): {
            "anomaly_score": a["anomaly_score"],
            "compactness": a["compactness"],
            "diagnosis": diagnose_anomaly(a)
        }
        for a in anomalies
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(anomalies_dict, f, indent=2, ensure_ascii=False)

    print(f"\n[Done] Saved {len(anomalies_dict)} flagged anomalies to {output_path}")


if __name__ == "__main__":
    main()
