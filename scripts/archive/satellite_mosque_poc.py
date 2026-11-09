"""
Proof-of-Concept: Satellite Imagery Mosque Detector & Visual Cue Analyzer
=========================================================================
Uses existing OpenStreetMap ground-truth mosques (`places_of_worship_sa.csv`)
to train a lightweight Computer Vision + Spatial Qibla classifier on Zoom-19
satellite imagery, and tests it on unverified candidate mosques from
`suggested_mosques_sa.csv`.

Visual Cues Extracted per Satellite Patch:
1. Qibla Wall Alignment: Probabilistic Hough Lines compared against exact
   geodesic Qibla bearing toward Mecca (21.4225° N, 39.8262° E).
2. Dome / Circular Roof Detection: Laplacian-of-Gaussian (LoG) & circular
   edge symmetry in the central building zone.
3. Minaret & Shadow Contrast: High-intensity pinnacle pixels paired with
   elongated dark shadow regions.
4. Architectural Texture & Color: HSV histogram & courtyard flatness features.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw
from skimage import color, feature, filters, transform
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import StratifiedKFold, cross_val_score

ROOT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT_DIR / "poc_satellite_output"
TILES_CACHE_DIR = OUTPUT_DIR / "tile_cache"

KAABA_LAT = 21.4225
KAABA_LON = 39.8262
ZOOM = 19
PATCH_SIZE = 320  # 320x320 px around target coordinate (~95m x 95m at Zoom 19)


def latlon_to_tile_px(lat: float, lon: float, zoom: int) -> tuple[int, int, int, int]:
    """Convert (lat, lon) to slippy map (tile_x, tile_y, pixel_x, pixel_y)."""
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    x_float = (lon + 180.0) / 360.0 * n
    y_float = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    tile_x = int(math.floor(x_float))
    tile_y = int(math.floor(y_float))
    px_x = int((x_float - tile_x) * 256)
    px_y = int((y_float - tile_y) * 256)
    return tile_x, tile_y, px_x, px_y


def compute_qibla_azimuth(lat: float, lon: float) -> float:
    """Return clockwise bearing in degrees (0=North, 90=East) from (lat, lon) to Kaaba."""
    phi1 = math.radians(lat)
    phi2 = math.radians(KAABA_LAT)
    dlon = math.radians(KAABA_LON - lon)
    y = math.sin(dlon) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlon)
    bearing = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
    return bearing


def fetch_single_tile(z: int, x: int, y: int, session: requests.Session) -> Image.Image:
    """Fetch a single 256x256 Esri World Imagery tile with disk caching."""
    TILES_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = TILES_CACHE_DIR / f"{z}_{x}_{y}.jpg"
    if cache_path.exists():
        return Image.open(cache_path).convert("RGB")

    url = f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
    headers = {"User-Agent": "SaudiMosqueMapPoC/1.0 (Academic/Hobbyist Research)"}
    resp = session.get(url, headers=headers, timeout=12)
    resp.raise_for_status()
    cache_path.write_bytes(resp.content)
    return Image.open(io.BytesIO(resp.content)).convert("RGB")


def fetch_centered_patch(lat: float, lon: float, zoom: int = ZOOM, size: int = PATCH_SIZE) -> Image.Image:
    """Fetch a 3x3 grid of tiles around (lat, lon) and crop an exact centered patch."""
    tx, ty, px, py = latlon_to_tile_px(lat, lon, zoom)
    canvas = Image.new("RGB", (256 * 3, 256 * 3))
    with requests.Session() as session:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                tile_img = fetch_single_tile(zoom, tx + dx, ty + dy, session)
                canvas.paste(tile_img, ((dx + 1) * 256, (dy + 1) * 256))

    center_x = 256 + px
    center_y = 256 + py
    half = size // 2
    return canvas.crop((center_x - half, center_y - half, center_x + half, center_y + half))


def angle_diff_mod90(a_deg: float, b_deg: float) -> float:
    """Minimum angular difference between two orientations modulo 90 degrees (rectangular walls)."""
    diff = abs(a_deg - b_deg) % 90.0
    return min(diff, 90.0 - diff)


def extract_visual_cues(img: Image.Image, lat: float, lon: float) -> tuple[np.ndarray, dict]:
    """
    Extract interpretable computer vision features & visual overlay metadata from a satellite patch.
    """
    rgb = np.asarray(img, dtype=np.float32) / 255.0
    gray = color.rgb2gray(rgb)
    hsv = color.rgb2hsv(rgb)
    h, w = gray.shape

    # Focus region: inner 65% of patch where the target building sits
    m = int(h * 0.175)
    inner_gray = gray[m : h - m, m : w - m]
    inner_hsv = hsv[m : h - m, m : w - m]

    # -------------------------------------------------------------------------
    # CUE 1: Qibla-Aligned Structural Lines (Hough Transform vs Qibla Bearing)
    # -------------------------------------------------------------------------
    qibla_bearing = compute_qibla_azimuth(lat, lon)
    edges = feature.canny(inner_gray, sigma=1.4)
    lines = transform.probabilistic_hough_line(
        edges, threshold=12, line_length=16, line_gap=4, rng=42
    )

    qibla_aligned_lines = []
    other_lines = []
    qibla_length_sum = 0.0
    total_length_sum = 1e-5

    for (x0, y0), (x1, y1) in lines:
        dx = x1 - x0
        dy = y1 - y0
        length = math.hypot(dx, dy)
        # Convert image vector (dx, dy where +y is South, +x is East) to compass bearing
        line_bearing = (math.degrees(math.atan2(dx, -dy)) + 360.0) % 360.0
        dev = angle_diff_mod90(line_bearing, qibla_bearing)
        total_length_sum += length

        # Shift coordinates back to full image frame
        full_line = ((x0 + m, y0 + m), (x1 + m, y1 + m))
        if dev <= 12.0:  # Within 12 degrees of Qibla or its perpendicular prayer hall wall
            qibla_aligned_lines.append(full_line)
            qibla_length_sum += length
        else:
            other_lines.append(full_line)

    qibla_alignment_ratio = qibla_length_sum / total_length_sum
    qibla_line_count = len(qibla_aligned_lines)

    # -------------------------------------------------------------------------
    # CUE 2: Dome / Circular Structure Detection (Laplacian of Gaussian Blobs)
    # -------------------------------------------------------------------------
    # Domes appear as bright or distinct circular structures of radius ~5 to 22 px at Zoom 19
    smoothed = filters.gaussian(inner_gray, sigma=1.2)
    blobs_bright = feature.blob_log(
        smoothed, min_sigma=4, max_sigma=16, num_sigma=6, threshold=0.045
    )
    blobs_dark = feature.blob_log(
        1.0 - smoothed, min_sigma=4, max_sigma=16, num_sigma=6, threshold=0.055
    )

    detected_domes = []
    for blob_list in (blobs_bright, blobs_dark):
        for by, bx, sigma in blob_list:
            radius = sigma * math.sqrt(2)
            # Check circular edge symmetry around the candidate dome
            cy, cx = int(by), int(bx)
            r_int = int(round(radius))
            if r_int < 5 or cy - r_int < 2 or cy + r_int >= inner_gray.shape[0] - 2:
                continue
            if cx - r_int < 2 or cx + r_int >= inner_gray.shape[1] - 2:
                continue
            patch_crop = inner_gray[cy - r_int : cy + r_int + 1, cx - r_int : cx + r_int + 1]
            # Radial symmetry check: compare patch with its 90-degree rotation
            rot90 = np.rot90(patch_crop)
            if patch_crop.shape == rot90.shape:
                symmetry_score = 1.0 - float(np.mean(np.abs(patch_crop - rot90)))
                if symmetry_score > 0.86:
                    detected_domes.append((cx + m, cy + m, r_int, symmetry_score))

    # Keep top strongest dome candidates
    detected_domes.sort(key=lambda x: x[3], reverse=True)
    detected_domes = detected_domes[:3]
    dome_count = len(detected_domes)
    max_dome_symmetry = detected_domes[0][3] if detected_domes else 0.0

    # -------------------------------------------------------------------------
    # CUE 3: Minaret / High-Contrast Shadow Signature
    # -------------------------------------------------------------------------
    # Minarets cast long, very dark shadows (<15th percentile brightness) next to bright structures
    dark_mask = inner_gray < 0.22
    bright_mask = inner_gray > 0.78
    shadow_fraction = float(np.mean(dark_mask))
    bright_roof_fraction = float(np.mean(bright_mask))
    contrast_std = float(np.std(inner_gray))

    # Local contrast (gradient magnitude)
    grad_mag = filters.sobel(inner_gray)
    mean_grad = float(np.mean(grad_mag))
    high_grad_ratio = float(np.mean(grad_mag > 0.12))

    # -------------------------------------------------------------------------
    # CUE 4: Roof & Courtyard Color/Texture Signature
    # -------------------------------------------------------------------------
    sat_channel = inner_hsv[:, :, 1]
    val_channel = inner_hsv[:, :, 2]
    mean_saturation = float(np.mean(sat_channel))
    mean_brightness = float(np.mean(val_channel))
    edge_density = float(np.mean(edges))

    feature_vector = np.array(
        [
            qibla_alignment_ratio,
            float(qibla_line_count),
             float(len(lines)),
            float(dome_count),
            max_dome_symmetry,
            shadow_fraction,
            bright_roof_fraction,
            contrast_std,
            mean_grad,
            high_grad_ratio,
            mean_saturation,
            mean_brightness,
            edge_density,
        ],
        dtype=np.float32,
    )

    metadata = {
        "qibla_bearing": round(qibla_bearing, 1),
        "qibla_alignment_ratio": round(qibla_alignment_ratio * 100, 1),
        "qibla_line_count": qibla_line_count,
        "total_lines": len(lines),
        "dome_count": dome_count,
        "detected_domes": detected_domes,
        "qibla_aligned_lines": qibla_aligned_lines,
        "other_lines": other_lines,
        "shadow_pct": round(shadow_fraction * 100, 1),
        "contrast_std": round(contrast_std, 3),
    }
    return feature_vector, metadata


def render_annotated_patch(img: Image.Image, meta: dict) -> Image.Image:
    """Draw detected domes, Qibla-aligned walls, and Qibla compass vector onto the satellite image."""
    annotated = img.copy().convert("RGBA")
    overlay = Image.new("RGBA", annotated.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # 1. Draw non-aligned lines faintly in yellow
    for (x0, y0), (x1, y1) in meta["other_lines"]:
        draw.line([(x0, y0), (x1, y1)], fill=(255, 215, 0, 75), width=1)

    # 2. Draw Qibla-aligned structural walls in bright green
    for (x0, y0), (x1, y1) in meta["qibla_aligned_lines"]:
        draw.line([(x0, y0), (x1, y1)], fill=(0, 255, 128, 210), width=2)

    # 3. Draw detected dome candidates in cyan circles
    for cx, cy, r, _sym in meta["detected_domes"]:
        draw.ellipse(
            [(cx - r - 2, cy - r - 2), (cx + r + 2, cy + r + 2)],
            outline=(0, 229, 255, 240),
            width=2,
        )
        draw.ellipse([(cx - 2, cy - 2), (cx + 2, cy + 2)], fill=(0, 229, 255, 255))

    # 4. Draw Qibla compass indicator in top-right corner
    compass_cx, compass_cy = annotated.width - 34, 34
    compass_r = 22
    draw.ellipse(
        [(compass_cx - compass_r, compass_cy - compass_r), (compass_cx + compass_r, compass_cy + compass_r)],
        fill=(15, 23, 42, 190),
        outline=(255, 255, 255, 180),
        width=1,
    )
    q_rad = math.radians(meta["qibla_bearing"])
    qx = compass_cx + int(math.sin(q_rad) * (compass_r - 4))
    qy = compass_cy - int(math.cos(q_rad) * (compass_r - 4))
    draw.line([(compass_cx, compass_cy), (qx, qy)], fill=(16, 185, 129, 255), width=3)
    draw.ellipse([(qx - 3, qy - 3), (qx + 3, qy + 3)], fill=(16, 185, 129, 255))

    return Image.alpha_composite(annotated, overlay).convert("RGB")


def pil_to_base64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def load_sample_coordinates() -> tuple[list[dict], list[dict], list[dict]]:
    """
    Select:
    - 28 Known Grand Mosques in Riyadh (way polygons from places_of_worship_sa.csv)
    - 28 Non-mosque urban background points (offset by ~280m from mosques, verified away from known mosques)
    - 12 Unverified candidate mosques from Wikidata (suggested_mosques_sa.csv)
    """
    positives = []
    all_mosque_coords = []

    with open(ROOT_DIR / "places_of_worship_sa.csv", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            lat = float(row["lat"])
            lon = float(row["lon"])
            if 24.55 < lat < 24.82 and 46.55 < lon < 46.85:
                all_mosque_coords.append((lat, lon))
                if (
                    row["osm_type"] == "way"
                    and ("جامع" in row["name"] or row["building"] == "mosque")
                    and len(positives) < 28
                ):
                    positives.append(
                        {
                            "id": row["id"],
                            "name": row["name"] or "Mosque",
                            "lat": lat,
                            "lon": lon,
                            "label": 1,
                        }
                    )

    # Generate negative urban samples ~300m away from each positive mosque, ensuring no known mosque is within 180m
    negatives = []
    offsets = [(0.0028, 0.0028), (-0.0028, 0.0025), (0.0025, -0.0028), (-0.0026, -0.0026)]
    for idx, pos in enumerate(positives):
        for dlat, dlon in offsets:
            cand_lat = pos["lat"] + dlat
            cand_lon = pos["lon"] + dlon
            too_close = any(
                math.hypot(cand_lat - mlat, cand_lon - mlon) < 0.0018
                for mlat, mlon in all_mosque_coords
            )
            if not too_close:
                negatives.append(
                    {
                        "id": f"neg_{idx}",
                        "name": f"Urban Block #{idx + 1} (Non-Mosque)",
                        "lat": round(cand_lat, 6),
                        "lon": round(cand_lon, 6),
                        "label": 0,
                    }
                )
                break

    # Load 12 unverified Wikidata candidate mosques in Riyadh
    candidates = []
    with open(ROOT_DIR / "suggested_mosques_sa.csv", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            lat = float(row["lat"])
            lon = float(row["lon"])
            nearest = float(row["nearest_osm_m"]) if row["nearest_osm_m"] else 999.0
            if (
                24.58 < lat < 24.80
                and 46.60 < lon < 46.82
                and "جامع" in row["name_ar"]
                and nearest > 250
            ):
                candidates.append(
                    {
                        "id": row["wikidata_id"],
                        "name": row["name_ar"],
                        "lat": lat,
                        "lon": lon,
                        "nearest_osm_m": int(nearest),
                    }
                )
                if len(candidates) >= 12:
                    break

    return positives, negatives, candidates


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print("1. Selecting Ground-Truth Mosques, Urban Non-Mosques, and Unverified Candidates...")
    positives, negatives, candidates = load_sample_coordinates()
    print(
        f"   Loaded {len(positives)} verified OSM mosques, "
        f"{len(negatives)} urban non-mosque locations, and "
        f"{len(candidates)} unverified Wikidata candidates."
    )

    all_items = positives + negatives + candidates
    print(f"2. Downloading Zoom-{ZOOM} Esri Satellite patches for {len(all_items)} locations...")

    def process_item(item: dict) -> dict:
        img = fetch_centered_patch(item["lat"], item["lon"])
        feats, meta = extract_visual_cues(img, item["lat"], item["lon"])
        annotated = render_annotated_patch(img, meta)
        return {
            **item,
            "img": img,
            "annotated": annotated,
            "features": feats,
            "meta": meta,
        }

    with ThreadPoolExecutor(max_workers=8) as pool:
        processed = list(pool.map(process_item, all_items))

    train_items = [p for p in processed if "label" in p]
    test_items = [p for p in processed if "label" not in p]

    X_train = np.vstack([p["features"] for p in train_items])
    y_train = np.array([p["label"] for p in train_items])

    print("3. Training Random Forest Classifier on Visual & Spatial Cues...")
    clf = RandomForestClassifier(
        n_estimators=200,
        max_depth=6,
        min_samples_leaf=2,
        random_state=42,
    )
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_scores = cross_val_score(clf, X_train, y_train, cv=cv, scoring="accuracy")
    cv_auc = cross_val_score(clf, X_train, y_train, cv=cv, scoring="roc_auc")

    clf.fit(X_train, y_train)
    print(f"   5-Fold Cross-Validation Accuracy: {cv_scores.mean() * 100:.1f}% (+/- {cv_scores.std() * 100:.1f}%)")
    print(f"   5-Fold ROC-AUC Score:             {cv_auc.mean() * 100:.1f}%")

    feature_names = [
        "Qibla Wall Alignment Ratio",
        "Qibla-Aligned Wall Count",
        "Total Roof Edge Lines",
        "Detected Circular Domes",
        "Max Dome Radial Symmetry",
        "Minaret/Courtyard Shadow Fraction",
        "Bright Roof Surface Fraction",
        "Brightness Contrast (StdDev)",
        "Mean Edge Gradient",
        "High-Contrast Edge Ratio",
        "Roof Color Saturation",
        "Mean Albedo / Brightness",
        "Canny Edge Density",
    ]
    importances = sorted(
        zip(feature_names, clf.feature_importances_), key=lambda x: x[1], reverse=True
    )
    print("\n   Top Visual Cues Learned by Model:")
    for name, imp in importances[:6]:
        print(f"   - {name:<34}: {imp * 100:5.1f}% importance")

    # Score both training positives (via out-of-bag / cross-val style) and unverified test candidates
    X_test = np.vstack([p["features"] for p in test_items])
    test_probs = clf.predict_proba(X_test)[:, 1]
    for item, prob in zip(test_items, test_probs):
        item["mosque_prob"] = round(float(prob) * 100, 1)

    test_items.sort(key=lambda x: x["mosque_prob"], reverse=True)

    # Save sample side-by-side images for artifact showcase
    showcase_dir = OUTPUT_DIR / "showcase"
    showcase_dir.mkdir(parents=True, exist_ok=True)
    for idx, item in enumerate(test_items[:6]):
        combined = Image.new("RGB", (PATCH_SIZE * 2 + 12, PATCH_SIZE), (15, 23, 42))
        combined.paste(item["img"], (0, 0))
        combined.paste(item["annotated"], (PATCH_SIZE + 12, 0))
        combined.save(showcase_dir / f"candidate_{idx + 1}_{item['id']}.jpg", quality=92)

    train_positives = [p for p in train_items if p["label"] == 1]
    for idx, item in enumerate(train_positives[:4]):
        combined = Image.new("RGB", (PATCH_SIZE * 2 + 12, PATCH_SIZE), (15, 23, 42))
        combined.paste(item["img"], (0, 0))
        combined.paste(item["annotated"], (PATCH_SIZE + 12, 0))
        combined.save(showcase_dir / f"verified_{idx + 1}.jpg", quality=92)

    # Save JSON summary + Interactive HTML Report
    summary_data = {
        "cv_accuracy_pct": round(float(cv_scores.mean() * 100), 1),
        "cv_roc_auc_pct": round(float(cv_auc.mean() * 100), 1),
        "train_positives": len(positives),
        "train_negatives": len(negatives),
        "feature_importances": [
            {"feature": k, "importance_pct": round(float(v * 100), 1)} for k, v in importances
        ],
        "candidates": [
            {
                "id": c["id"],
                "name": c["name"],
                "lat": c["lat"],
                "lon": c["lon"],
                "nearest_osm_m": c["nearest_osm_m"],
                "mosque_prob": c["mosque_prob"],
                "qibla_alignment_ratio": c["meta"]["qibla_alignment_ratio"],
                "qibla_line_count": c["meta"]["qibla_line_count"],
                "dome_count": c["meta"]["dome_count"],
                "qibla_bearing": c["meta"]["qibla_bearing"],
            }
            for c in test_items
        ],
    }
    (OUTPUT_DIR / "poc_results.json").write_text(
        json.dumps(summary_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Build interactive HTML report
    cards_html = []
    for c in test_items:
        raw_b64 = pil_to_base64(c["img"])
        ann_b64 = pil_to_base64(c["annotated"])
        badge_color = "#10b981" if c["mosque_prob"] >= 70 else ("#f59e0b" if c["mosque_prob"] >= 45 else "#ef4444")
        cards_html.append(
            f"""
            <div class="card">
              <div class="card-header">
                <div>
                  <h3>{c['name']} <span class="qid">({c['id']})</span></h3>
                  <p class="coords">📍 {c['lat']:.5f}, {c['lon']:.5f} · Nearest OSM Mosque: {c['nearest_osm_m']}m away</p>
                </div>
                <div class="prob-badge" style="background:{badge_color}">
                  {c['mosque_prob']}% Mosque Match
                </div>
              </div>
              <div class="img-pair">
                <div>
                  <img src="{raw_b64}" alt="Raw Satellite" />
                  <span class="caption">Raw Zoom-19 Satellite Tile</span>
                </div>
                <div>
                  <img src="{ann_b64}" alt="AI Visual Cues" />
                  <span class="caption">AI Cues: <b style="color:#10b981">Green=Qibla Walls</b> · <b style="color:#00e5ff">Cyan=Domes</b></span>
                </div>
              </div>
              <div class="metrics">
                <span>🧭 Qibla Bearing: <b>{c['meta']['qibla_bearing']}°</b></span>
                <span>📐 Qibla-Aligned Walls: <b>{c['meta']['qibla_alignment_ratio']}% ({c['meta']['qibla_line_count']} lines)</b></span>
                <span>🕌 Circular Domes: <b>{c['meta']['dome_count']}</b></span>
                <span>🌗 Shadow Ratio: <b>{c['meta']['shadow_pct']}%</b></span>
              </div>
            </div>
            """
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Satellite Mosque AI Detector — Proof of Concept</title>
  <style>
    body {{ font-family: system-ui, -apple-system, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 32px; }}
    .container {{ max-width: 1200px; margin: 0 auto; }}
    h1 {{ margin-bottom: 8px; font-size: 28px; }}
    .subtitle {{ color: #94a3b8; margin-bottom: 24px; }}
    .stats-bar {{ display: flex; gap: 16px; margin-bottom: 28px; flex-wrap: wrap; }}
    .stat-box {{ background: #1e293b; border: 1px solid #334155; padding: 16px 20px; border-radius: 12px; flex: 1; min-width: 180px; }}
    .stat-val {{ font-size: 26px; font-weight: 700; color: #38bdf8; }}
    .stat-label {{ font-size: 13px; color: #94a3b8; margin-top: 4px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(540px, 1fr)); gap: 20px; }}
    .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 14px; padding: 18px; }}
    .card-header {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; }}
    .card-header h3 {{ margin: 0; font-size: 18px; }}
    .qid {{ color: #64748b; font-size: 14px; font-weight: normal; }}
    .coords {{ margin: 4px 0 0; font-size: 13px; color: #94a3b8; }}
    .prob-badge {{ padding: 6px 12px; border-radius: 999px; font-weight: 700; font-size: 14px; color: #0f172a; white-space: nowrap; }}
    .img-pair {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    .img-pair img {{ width: 100%; border-radius: 8px; border: 1px solid #475569; display: block; }}
    .caption {{ display: block; font-size: 12px; color: #cbd5e1; margin-top: 6px; text-align: center; }}
    .metrics {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 14px; padding-top: 12px; border-top: 1px solid #334155; font-size: 13px; color: #cbd5e1; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>🛰️ Satellite Mosque AI Detector — Proof of Concept</h1>
    <p class="subtitle">Trained on {len(positives)} verified OSM mosques & {len(negatives)} urban non-mosque tiles in Riyadh (Zoom 19 Esri World Imagery). Tested on {len(test_items)} unmapped Wikidata candidates.</p>
    <div class="stats-bar">
      <div class="stat-box"><div class="stat-val">{cv_scores.mean() * 100:.1f}%</div><div class="stat-label">5-Fold CV Accuracy</div></div>
      <div class="stat-box"><div class="stat-val">{cv_auc.mean() * 100:.1f}%</div><div class="stat-label">ROC-AUC Score</div></div>
      <div class="stat-box"><div class="stat-val">{sum(1 for c in test_items if c['mosque_prob'] >= 70)} / {len(test_items)}</div><div class="stat-label">High-Confidence Unmapped Mosques Found</div></div>
      <div class="stat-box"><div class="stat-val">$0.00</div><div class="stat-label">Total Compute & Imagery Cost</div></div>
    </div>
    <div class="grid">
      {''.join(cards_html)}
    </div>
  </div>
</body>
</html>
"""
    report_path = OUTPUT_DIR / "satellite_mosque_poc.html"
    report_path.write_text(html, encoding="utf-8")
    print(f"\n4. Done! Visual report saved to: {report_path}")


if __name__ == "__main__":
    main()
