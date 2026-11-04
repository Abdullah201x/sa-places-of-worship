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

import math
import os
import time

import numpy as np
import osmium
from shapely.geometry import Point, Polygon
from sklearn.ensemble import IsolationForest

from common import (BASE_DIR, axis_deviation, calculate_qibla_azimuth, configure_utf8_output,
                    find_pbf, is_worship_tagged, load_boundary, ring_centroid, to_metres,
                    update_summary, write_json)

configure_utf8_output()

# Default alert threshold, used only for the console summary. The dashboard
# applies its own user-adjustable threshold to qibla_dev.
QIBLA_ALERT_DEG = 20.0
KAABA_LAT = 21.422487
KAABA_LON = 39.826206


def get_building_azimuth_and_deviation(poly, qibla_deg):
    """
    Finds building's principal orientation angle (Minimum Bounding Box)
    and computes the minimum deviation from the Qibla axis (0 to 45 degrees).
    """
    mrr = poly.minimum_rotated_rectangle
    coords = list(mrr.exterior.coords)[:-1]
    if len(coords) < 4:
        return None, None
    edges = []
    for i in range(len(coords)):
        p1, p2 = coords[i], coords[(i + 1) % len(coords)]
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        length = math.hypot(dx, dy)
        if length < 0.5:
            continue
        angle = math.degrees(math.atan2(dx, dy)) % 180.0
        edges.append((angle, length))
    if not edges:
        return None, None

    # Find the edge with minimum deviation to Qibla (or perpendicular to Qibla)
    best_dev = 999.0
    best_angle = edges[0][0]
    for angle, length in edges:
        dev = axis_deviation(angle, qibla_deg)
        if dev < best_dev:
            best_dev = dev
            best_angle = angle
    return round(best_angle, 1), round(best_dev, 1)


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

        if not is_worship_tagged(tags):
            return

        try:
            coords = [(n.lon, n.lat) for n in w.nodes]
        except osmium.InvalidLocationError:
            return
        n_nodes = len(coords)
        if n_nodes < 4:
            return

        centroid_lon, centroid_lat = ring_centroid(coords)

        # Boundary filter
        if not (self.minx <= centroid_lon <= self.maxx and self.miny <= centroid_lat <= self.maxy):
            return
        if not self.boundary_prep.contains(Point(centroid_lon, centroid_lat)):
            return

        # Projected coordinates in meters with local latitude scaling
        m_lon = 111_320.0 * math.cos(math.radians(centroid_lat))
        m_lat = 110_574.0
        coords_m = [(x * m_lon, y * m_lat) for x, y in coords]
        poly = Polygon(coords_m)
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

        # FEATURE 6: Qibla Azimuth & Principal Building Axis Deviation
        # Exempt features within 500m of the Kaaba where azimuth becomes degenerate
        d_kaaba = math.hypot(
            (centroid_lat - KAABA_LAT) * m_lat,
            (centroid_lon - KAABA_LON) * m_lon
        )
        qibla_az = calculate_qibla_azimuth(centroid_lat, centroid_lon)
        if d_kaaba < 500.0:
            bldg_az = 0.0
            qibla_dev = 0.0
        else:
            bldg_az, qibla_dev = get_building_azimuth_and_deviation(poly, qibla_az)

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
            "qibla_azimuth": round(qibla_az, 1),
            "building_azimuth": bldg_az,
            "qibla_dev": qibla_dev if qibla_dev is not None else 0.0,
        })

    def area(self, a):
        if a.from_way() or not is_worship_tagged(a.tags):
            return
        if a.tags.get('place_of_worship') == 'musalla':
            return
        polys = []
        try:
            for outer in a.outer_rings():
                shell = [(nd.lon, nd.lat) for nd in outer]
                holes = [[(nd.lon, nd.lat) for nd in inner] for inner in a.inner_rings(outer)]
                p = Polygon(shell, holes=holes)
                if not p.is_valid:
                    p = p.buffer(0)
                if p.is_valid and p.area > 0:
                    polys.append(p)
        except osmium.InvalidLocationError:
            return
        if not polys:
            return

        for p in polys:
            centroid_lat = p.centroid.y
            centroid_lon = p.centroid.x
            if not (self.minx <= centroid_lon <= self.maxx and self.miny <= centroid_lat <= self.maxy):
                continue
            if not self.boundary_prep.contains(Point(centroid_lon, centroid_lat)):
                continue

            m_lon = 111_320.0 * math.cos(math.radians(centroid_lat))
            m_lat = 110_574.0
            shell_m = [(x * m_lon, y * m_lat) for x, y in p.exterior.coords]
            holes_m = [[(x * m_lon, y * m_lat) for x, y in h.coords] for h in p.interiors]
            poly_m = Polygon(shell_m, holes=holes_m)
            area_m2 = poly_m.area
            perimeter_m = poly_m.length
            if area_m2 <= 0 or perimeter_m <= 0:
                continue

            compactness = (4.0 * math.pi * area_m2) / (perimeter_m ** 2)
            n_nodes = len(p.exterior.coords) + sum(len(h.coords) for h in p.interiors)
            area_per_node = area_m2 / max(n_nodes, 1)

            d_kaaba = math.hypot((centroid_lat - KAABA_LAT) * m_lat, (centroid_lon - KAABA_LON) * m_lon)
            qibla_az = calculate_qibla_azimuth(centroid_lat, centroid_lon)
            if d_kaaba < 500.0:
                bldg_az = 0.0
                qibla_dev = 0.0
            else:
                bldg_az, qibla_dev = get_building_azimuth_and_deviation(poly_m, qibla_az)

            name = a.tags.get('name', a.tags.get('name:ar', a.tags.get('name:en', 'Unnamed Mosque')))
            self.records.append({
                "osm_id": a.orig_id(),
                "name": name,
                "centroid": (round(centroid_lat, 6), round(centroid_lon, 6)),
                "area_m2": round(area_m2, 1),
                "perimeter_m": round(perimeter_m, 1),
                "compactness": round(compactness, 4),
                "node_count": n_nodes,
                "area_per_node": round(area_per_node, 1),
                "qibla_azimuth": round(qibla_az, 1),
                "building_azimuth": bldg_az,
                "qibla_dev": qibla_dev if qibla_dev is not None else 0.0,
            })


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
            min(r["qibla_dev"], 45.0) / 45.0             # Normalized Qibla deviation (0 to 1)
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
        n_jobs=1                    # Single process to preserve VPS budget
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
        # Model verdict only. Qibla misalignment is reported as its own issue
        # in the dashboard (with a user-adjustable threshold), so folding it in
        # here would list the same buildings under two filters.
        r["is_anomaly"] = bool(predictions[i] == -1)

    # Sort so the most severe anomalies appear first
    anomalies = [r for r in records if r["is_anomaly"]]
    anomalies.sort(key=lambda x: x["anomaly_score"])

    return anomalies, records


def diagnose_anomaly(r):
    """Human-readable (Arabic, English) explanation of why a footprint was flagged."""
    reasons = []

    # Qibla deviation is one of the model's features, so mention it when it
    # likely contributed. Severe cases are also a separate dashboard issue.
    q_dev = r.get("qibla_dev", 0.0)
    if q_dev >= QIBLA_ALERT_DEG:
        reasons.append((f"انحراف حاد عن القبلة ({q_dev}° — سمت القبلة {r.get('qibla_azimuth')}° مقابل {r.get('building_azimuth')}° لمحور المبنى)",
                        f"severe Qibla deviation ({q_dev}°: Qibla bearing {r.get('qibla_azimuth')}° vs building axis {r.get('building_azimuth')}°)"))
    elif q_dev >= 15.0:
        reasons.append((f"انحراف ملحوظ عن القبلة ({q_dev}°)", f"noticeable Qibla deviation ({q_dev}°)"))

    if r["node_count"] > 100:
        reasons.append((f"عدد عقد مفرط جداً ({r['node_count']} عقدة — رسم تفصيلي معقد أو استيراد CAD)",
                        f"excessive node count ({r['node_count']} nodes: over-detailed drawing or CAD import)"))
    elif r["node_count"] > 40 and r["area_m2"] < 1500:
        reasons.append((f"كثافة عقد عالية بالنسبة للمساحة ({r['node_count']} عقدة لمساحة {r['area_m2']} م²)",
                        f"high node density for its size ({r['node_count']} nodes for {r['area_m2']} m²)"))

    if r["compactness"] < 0.35:
        reasons.append((f"شكل غير متناسق أو مفرط الاستطالة (Compactness={r['compactness']:.2f})",
                        f"irregular or very elongated shape (compactness={r['compactness']:.2f})"))
    elif r["compactness"] < 0.45 and r["node_count"] > 25:
        reasons.append((f"محيط متعرج كثير الانكسارات (Compactness={r['compactness']:.2f})",
                        f"jagged outline with many corners (compactness={r['compactness']:.2f})"))

    if r["area_m2"] < 25:
        reasons.append((f"مساحة متناهية الصغر ({r['area_m2']} م²)", f"tiny area ({r['area_m2']} m²)"))
    elif r["area_m2"] > 15000:
        reasons.append((f"مساحة استثنائية الضخامة ({r['area_m2']:,} م²)", f"exceptionally large area ({r['area_m2']:,} m²)"))

    if not reasons:
        reasons.append(("انحراف مركب في تناسق النسبة بين المساحة والمحيط والعقد",
                        "unusual combination of area, perimeter and node count"))
    return " • ".join(ar for ar, _ in reasons), " • ".join(en for _, en in reasons)


def main():
    pbf_path = find_pbf(BASE_DIR)
    output_path = os.path.join(BASE_DIR, "mosque_anomalies.json")

    print("=" * 65)
    print("  MOSQUE GEOMETRY ANOMALY DETECTION (ISOLATION FOREST - ML)")
    print("=" * 65)
    print(f"OSM PBF Source: {pbf_path}")

    boundary_poly, boundary_prep, _ = load_boundary(BASE_DIR)

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
        reason = diagnose_anomaly(a)[0]
        lat, lon = a["centroid"]
        osm_url = f"https://www.openstreetmap.org/way/{a['osm_id']}"
        josm_url = f"http://127.0.0.1:8111/load_and_zoom?left={lon-0.001}&right={lon+0.001}&top={lat+0.001}&bottom={lat-0.001}&select=way{a['osm_id']}"
        
        print(f"\n#{rank} [{a['name']}] (OSM Way ID: {a['osm_id']})")
        print(f"   • Anomaly Score: {a['anomaly_score']} (Lower = more abnormal)")
        print(f"   • Area: {a['area_m2']:,} m² | Perimeter: {a['perimeter_m']:,} m | Nodes: {a['node_count']} | Compactness: {a['compactness']}")
        print(f"   • Diagnosis: {reason}")
        print(f"   • OSM Link: {osm_url}")
        print(f"   • JOSM: {josm_url}")

    # Save to JSON
    # Map by osm_id so it can be merged directly into the dashboard
    # We save all scored mosque footprints with their exact Qibla deviation so the UI can dynamically filter and sort
    anomalies_dict = {}
    for r in all_scored:
        diagnosis_ar, diagnosis_en = diagnose_anomaly(r)
        anomalies_dict[str(r["osm_id"])] = {
            "anomaly_score": r["anomaly_score"],
            "is_anomaly": r["is_anomaly"],
            "compactness": r["compactness"],
            "area_m2": r["area_m2"],
            "node_count": r["node_count"],
            "qibla_dev": r["qibla_dev"],
            "qibla_az": r["qibla_azimuth"],
            "bldg_az": r["building_azimuth"],
            "diagnosis": diagnosis_ar,
            "diagnosis_en": diagnosis_en,
        }

    write_json(output_path, anomalies_dict)

    flagged_count = sum(1 for r in anomalies_dict.values() if r["is_anomaly"])
    qibla_flagged = sum(1 for r in anomalies_dict.values() if r["qibla_dev"] >= QIBLA_ALERT_DEG)
    update_summary("anomalies", {"count": len(anomalies_dict), "flagged": flagged_count,
                                 "qibla_over_threshold": qibla_flagged}, pbf_path)
    print(f"\n[Done] Saved {len(anomalies_dict):,} mosque footprints ({flagged_count} ML-flagged, "
          f"{qibla_flagged} with Qibla dev >= {QIBLA_ALERT_DEG:.0f}°) to {output_path}")


if __name__ == "__main__":
    main()
