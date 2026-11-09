"""
Phase 3: Autonomous Country-Wide Coverage Gap Scanner with YOLOv11x v2
======================================================================
100% Independent Satellite Vision (Zero External University Dependencies):

1. Reads pure OpenStreetMap residential coverage gaps from `worship_gaps_sa.csv`
   (dense living communities with roads & houses far from any mapped place of worship).
2. Targets pure residential cluster centers across all 13 Saudi provinces.
3. Downloads high-resolution Zoom-19 satellite imagery (Esri + Mapbox) with
   continuous Web Mercator Qibla-rotation normalization.
4. Executes YOLOv11x v2 (`best_v2.pt`) trained at 640px.
5. Inverts rotated pixels back to exact geographic coordinates (lat, lon).
6. Strict spatial guard: rejects any detection within 100m of an existing OSM mosque.
7. Applies Geographic Non-Maximum Suppression (60m) and flags 🌟 Dual-Confirmed
   detections verified independently across both Esri & Mapbox.
8. Exports `ai_detected_mosques_sa.geojson` + interactive verification HTML report.
"""

from __future__ import annotations

import argparse
import base64
import collections
import csv
import io
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw
from shapely.geometry import Point, shape
from shapely.prepared import prep
from ultralytics import YOLO

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "pipeline"))
sys.path.insert(0, str(ROOT_DIR / "scripts"))

from common import calculate_qibla_azimuth, configure_utf8_output  # noqa: E402
from step1_1_generate_bboxes import (  # noqa: E402
    PATCH_SIZE,
    ZOOM,
    _is_placeholder_tile,
    fetch_single_tile,
    latlon_to_global_px,
)

configure_utf8_output()

DEFAULT_WEIGHTS = (
    ROOT_DIR / "poc_satellite_output" / "best_v5_obb.pt"
    if (ROOT_DIR / "poc_satellite_output" / "best_v5_obb.pt").exists()
    else ROOT_DIR / "poc_satellite_output" / "best_obb.pt"
    if (ROOT_DIR / "poc_satellite_output" / "best_obb.pt").exists()
    else (
        ROOT_DIR / "poc_satellite_output" / "best_obb.onnx"
        if (ROOT_DIR / "poc_satellite_output" / "best_obb.onnx").exists()
        else (
            ROOT_DIR / "poc_satellite_output" / "best_v3.pt"
            if (ROOT_DIR / "poc_satellite_output" / "best_v3.pt").exists()
            else (
                ROOT_DIR / "poc_satellite_output" / "best_v2.pt"
                if (ROOT_DIR / "poc_satellite_output" / "best_v2.pt").exists()
                else (ROOT_DIR / "poc_satellite_output" / "best.pt")
            )
        )
    )
)
GAPS_CSV = ROOT_DIR / "worship_gaps_sa.csv"
OUTPUT_GEOJSON = ROOT_DIR / "ai_detected_mosques_sa.geojson"
OUTPUT_REPORT = ROOT_DIR / "poc_satellite_output" / "phase3_gap_scan_report.html"

OUTER_HALF = 370  # 740x740 window for borderless Qibla rotation


# ---------------------------------------------------------------------------
# Coordinate Inversion Math: Rotated Patch Pixels -> Exact Geographic Lat/Lon
# ---------------------------------------------------------------------------


def rotated_patch_px_to_latlon(
    px_x: float,
    px_y: float,
    center_lat: float,
    center_lon: float,
    qibla_bearing: float,
    zoom: int = ZOOM,
    patch_size: int = PATCH_SIZE,
) -> tuple[float, float]:
    """
    Invert the borderless Qibla rotation and continuous Web Mercator projection
    to map a detected bounding box pixel (px_x, px_y) back into exact (lat, lon).
    """
    cx, cy = patch_size / 2.0, patch_size / 2.0
    rx = px_x - cx
    ry = px_y - cy

    rad = math.radians(qibla_bearing)
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)

    # Invert counter-clockwise rotation by qibla_bearing:
    # rx = dx * cos_a + dy * sin_a
    # ry = -dx * sin_a + dy * cos_a
    # -> dx = rx * cos_a - ry * sin_a
    # -> dy = rx * sin_a + ry * cos_a
    dx = rx * cos_a - ry * sin_a
    dy = rx * sin_a + ry * cos_a

    cx_global, cy_global = latlon_to_global_px(center_lat, center_lon, zoom)
    gx = cx_global + dx
    gy = cy_global + dy

    n = 256.0 * (2.0**zoom)
    lon = (gx / n) * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1.0 - 2.0 * gy / n)))
    lat = math.degrees(lat_rad)
    return round(lat, 6), round(lon, 6)


# ---------------------------------------------------------------------------
# Gap-cell tiling
# ---------------------------------------------------------------------------

GAP_GRID_DEG = 0.004  # must match pipeline/calculate_gaps.py GRID_SIZE (~405 x 442 m cells)
SCAN_MAX_STRIDE_M = 105.0  # patch is ~130-146 m wide -> >=25 m overlap so edge mosques appear whole


def cell_scan_points(grid_x: int, grid_y: int, zoom: int = ZOOM, patch_size: int = PATCH_SIZE) -> list[tuple[str, float, float]]:
    """
    Patch centres that cover the entire gap cell with overlapping Qibla-rotated patches.

    The previous NW/NE/SW/SE scheme put centres 250 m from the cell centre, assuming 1 km
    cells; with the real 0.004 deg cells the four 140 m patches landed almost entirely in
    neighbouring cells and covered ~2% of the gap itself. A rotated square patch always
    covers at least its inscribed circle, so we tile with a stride below the patch width.
    """
    lon0, lat0 = grid_x * GAP_GRID_DEG, grid_y * GAP_GRID_DEG
    lat_c = lat0 + GAP_GRID_DEG / 2
    m_lat = 110_574.0
    m_lon = 111_320.0 * math.cos(math.radians(lat_c))
    mpp = 156543.03392 * math.cos(math.radians(lat_c)) / (2**zoom)
    patch_m = patch_size * mpp

    def axis(extent_m: float) -> list[float]:
        n = max(1, math.ceil(max(0.0, extent_m - patch_m) / SCAN_MAX_STRIDE_M) + 1)
        if n == 1:
            return [extent_m / 2]
        first, last = patch_m / 2, extent_m - patch_m / 2
        return [first + i * (last - first) / (n - 1) for i in range(n)]

    pts = []
    for iy, y_m in enumerate(axis(GAP_GRID_DEG * m_lat)):
        for ix, x_m in enumerate(axis(GAP_GRID_DEG * m_lon)):
            pts.append((f"r{iy}c{ix}", round(lat0 + y_m / m_lat, 6), round(lon0 + x_m / m_lon, 6)))
    return pts


# ---------------------------------------------------------------------------
# Borderless Tile Fetcher
# ---------------------------------------------------------------------------


def fetch_borderless_patch(
    lat: float,
    lon: float,
    qibla_bearing: float,
    session: requests.Session,
    zoom: int = ZOOM,
    patch_size: int = PATCH_SIZE,
    provider: str = "esri",
) -> tuple[Image.Image | None, Image.Image | None]:
    """
    Returns (raw_unrotated_740, rotated_512_crop).
    """
    gx, gy = latlon_to_global_px(lat, lon, zoom)
    ix, iy = int(round(gx)), int(round(gy))

    tx0 = (ix - OUTER_HALF) // 256
    tx1 = (ix + OUTER_HALF - 1) // 256
    ty0 = (iy - OUTER_HALF) // 256
    ty1 = (iy + OUTER_HALF - 1) // 256

    canvas_w = (tx1 - tx0 + 1) * 256
    canvas_h = (ty1 - ty0 + 1) * 256
    canvas = Image.new("RGB", (canvas_w, canvas_h))

    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            tile_img = fetch_single_tile(zoom, tx, ty, session, provider=provider)
            canvas.paste(tile_img, ((tx - tx0) * 256, (ty - ty0) * 256))

    x_off = (ix - OUTER_HALF) - tx0 * 256
    y_off = (iy - OUTER_HALF) - ty0 * 256
    outer_size = OUTER_HALF * 2
    crop_740 = canvas.crop((x_off, y_off, x_off + outer_size, y_off + outer_size))

    if _is_placeholder_tile(crop_740):
        return None, None

    rot_740 = crop_740.rotate(qibla_bearing, resample=Image.Resampling.BICUBIC, expand=False)
    margin = OUTER_HALF - (patch_size // 2)
    crop_512 = rot_740.crop((margin, margin, margin + patch_size, margin + patch_size))
    return crop_740, crop_512


# ---------------------------------------------------------------------------
# Spatial Proximity & Reference Indexes
# ---------------------------------------------------------------------------


def build_reference_indexes() -> tuple[
    dict[tuple[int, int], list[tuple[float, float]]],
    list[tuple[str, str, str, object, tuple[float, float, float, float]]],
]:
    """
    Build:
    1. OSM verified mosques spatial grid (for strict 100m exclusion guard).
    2. Saudi provinces boundaries (for regional routing and reporting).
    Note: 100% independent from any third-party/university datasets.
    """
    osm_grid: dict[tuple[int, int], list[tuple[float, float]]] = collections.defaultdict(list)
    places_fc = json.loads((ROOT_DIR / "places_of_worship_sa.geojson").read_text(encoding="utf-8"))
    for f in places_fc["features"]:
        lon, lat = f["geometry"]["coordinates"]
        gx, gy = int(math.floor(lon / 0.002)), int(math.floor(lat / 0.002))
        osm_grid[(gx, gy)].append((lat, lon))

    regions_fc = json.loads((ROOT_DIR / "sa_regions.geojson").read_text(encoding="utf-8"))
    regions = []
    for f in regions_fc["features"]:
        geom = shape(f["geometry"])
        regions.append(
            (
                f["properties"]["code"],
                f["properties"]["name_en"],
                f["properties"]["name"],
                prep(geom),
                geom.bounds,
            )
        )
    return osm_grid, regions


def is_near_osm_mosque(
    lat: float, lon: float, osm_grid: dict[tuple[int, int], list[tuple[float, float]]], max_dist_m: float = 100.0
) -> bool:
    gx, gy = int(math.floor(lon / 0.002)), int(math.floor(lat / 0.002))
    m_lat = 110_574.0
    m_lon = 111_320.0 * math.cos(math.radians(lat))
    r2 = max_dist_m * max_dist_m
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for mlat, mlon in osm_grid.get((gx + dx, gy + dy), ()):
                dy_m = (lat - mlat) * m_lat
                dx_m = (lon - mlon) * m_lon
                if dx_m * dx_m + dy_m * dy_m <= r2:
                    return True
    return False


def find_region_code(
    lat: float, lon: float, regions: list[tuple[str, str, str, object, tuple[float, float, float, float]]]
) -> tuple[str, str]:
    pt = Point(lon, lat)
    for code, name_en, _, p_geom, (bx0, by0, bx1, by1) in regions:
        if bx0 <= lon <= bx1 and by0 <= lat <= by1 and p_geom.contains(pt):
            return code, name_en
    return "SA-XX", "Unknown"


# ---------------------------------------------------------------------------
# Geographic Non-Maximum Suppression (Deduplication within 60m)
# ---------------------------------------------------------------------------


def apply_geographic_nms(detections: list[dict], min_distance_m: float = 60.0) -> list[dict]:
    """
    Sort detections by confidence descending and drop lower-confidence duplicates within min_distance_m.
    If detected across both providers, merge and tag as cross-verified.
    """
    sorted_dets = sorted(detections, key=lambda d: d["confidence"], reverse=True)
    kept: list[dict] = []
    m_lat = 110_574.0

    for det in sorted_dets:
        lat, lon = det["lat"], det["lon"]
        m_lon = 111_320.0 * math.cos(math.radians(lat))
        matched = None
        for k in kept:
            dy_m = (lat - k["lat"]) * m_lat
            dx_m = (lon - k["lon"]) * m_lon
            if dx_m * dx_m + dy_m * dy_m <= min_distance_m * min_distance_m:
                matched = k
                break
        if matched is None:
            det["cross_verified"] = False
            prov = det.get("provider", "esri")
            det["provider_label"] = "Mapbox Satellite" if prov == "mapbox" else "Esri World Imagery"
            kept.append(det)
        else:
            # If from a different provider, mark as cross-verified!
            if matched.get("provider") != det.get("provider"):
                matched["cross_verified"] = True
                matched["provider_label"] = "🌟 Dual-Confirmed (Esri + Mapbox)"
                matched["confidence"] = round(min(0.99, max(matched["confidence"], det["confidence"]) + 0.03), 3)
    return kept


# ---------------------------------------------------------------------------
# Visual Annotation & Card Renderer for HTML Report
# ---------------------------------------------------------------------------


def annotate_detection(patch_512: Image.Image, box: list[float], conf: float, qibla_bearing: float) -> Image.Image:
    vis = patch_512.copy().convert("RGBA")
    ov = Image.new("RGBA", vis.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(ov)

    x0, y0, x1, y1 = box
    draw.rectangle([x0, y0, x1, y1], fill=(16, 185, 129, 45), outline=(16, 185, 129, 255), width=3)

    # Corner brackets
    c_len = 12
    for cx, cy, sx, sy in [(x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)]:
        draw.line([(cx, cy), (cx + sx * c_len, cy)], fill=(52, 211, 153, 255), width=4)
        draw.line([(cx, cy), (cx, cy + sy * c_len)], fill=(52, 211, 153, 255), width=4)

    # Qibla UP compass indicator
    ccx, ccy, cr = vis.width - 36, 36, 22
    draw.ellipse([(ccx - cr, ccy - cr), (ccx + cr, ccy + cr)], fill=(15, 23, 42, 200), outline=(255, 255, 255, 190))
    draw.line([(ccx, ccy + 10), (ccx, ccy - cr + 5)], fill=(250, 204, 21, 255), width=3)
    draw.ellipse([(ccx - 3, ccy - cr + 2), (ccx + 3, ccy - cr + 8)], fill=(250, 204, 21, 255))

    return Image.alpha_composite(vis, ov).convert("RGB")


def pil_to_base64(img: Image.Image, max_side: int = 340) -> str:
    if img.width > max_side:
        img = img.resize((max_side, max_side), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=86)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


# ---------------------------------------------------------------------------
# Main Scanner Routine
# ---------------------------------------------------------------------------


def scan_gaps(
    weights_path: Path,
    conf_threshold: float = 0.35,
    limit: int = 500,
    min_urgency: float = 70.0,
    min_road_m: float = 1200.0,
    max_road_m: float = 12000.0,
    region_filter: str | None = None,
    provider: str = "esri",
    output_geojson: Path = OUTPUT_GEOJSON,
    output_html: Path = OUTPUT_REPORT,
) -> None:
    t0 = time.time()
    print("=" * 78)
    print("PHASE 3: AI SATELLITE MOSQUE SCANNER (YOLOv11x)")
    print("=" * 78)

    # 1. Load YOLO Model
    print(f"1. Loading trained YOLO model from {weights_path.name}...")
    model = YOLO(str(weights_path))

    # 2. Build Reference Spatial Indexes
    print("2. Building spatial guard against existing OSM mosques (strict 100m exclusion)...")
    osm_grid, regions = build_reference_indexes()

    # 3. Filter Candidate Gap Cells from worship_gaps_sa.csv
    print(
        f"3. Filtering high-urgency residential coverage gaps "
        f"(Urgency >= {min_urgency}, Road: {min_road_m:,.0f}m - {max_road_m:,.0f}m)..."
    )
    raw_cells = list(csv.DictReader(open(GAPS_CSV, encoding="utf-8-sig")))

    cands_by_region: dict[str, list[dict]] = collections.defaultdict(list)
    for r in raw_cells:
        urg = float(r["urgency_score"])
        road = float(r["road_length_m"])
        if urg >= min_urgency and min_road_m <= road <= max_road_m:
            lat = float(r["lat"])
            lon = float(r["lon"])
            rcode, rname = find_region_code(lat, lon, regions)
            if region_filter and rcode != region_filter:
                continue
            rank = urg * math.sqrt(road)
            cands_by_region[rcode].append(
                {
                    "grid_x": r["grid_x"],
                    "grid_y": r["grid_y"],
                    "lat": lat,
                    "lon": lon,
                    "urgency": urg,
                    "road_m": road,
                    "region_code": rcode,
                    "region_name": rname,
                    "rank": rank,
                }
            )

    # Sort candidates in each region by rank descending
    for rcode in cands_by_region:
        cands_by_region[rcode].sort(key=lambda c: c["rank"], reverse=True)

    # Balanced round-robin across regions so all provinces get representative coverage
    cands = []
    if region_filter:
        cands = cands_by_region.get(region_filter, [])
        if limit > 0 and len(cands) > limit:
            cands = cands[:limit]
    else:
        reg_keys = sorted(cands_by_region.keys())
        idx = 0
        while True:
            added_any = False
            for k in reg_keys:
                if idx < len(cands_by_region[k]):
                    cands.append(cands_by_region[k][idx])
                    added_any = True
                    if limit > 0 and len(cands) >= limit:
                        break
            if not added_any or (limit > 0 and len(cands) >= limit):
                break
            idx += 1

    print(
        f"   Selected {len(cands):,} high-priority residential gap cells "
        f"across {len(set(c['region_code'] for c in cands))} regions "
        f"(Filtered from {len(raw_cells):,} total cells across Saudi Arabia)."
    )

    # Tile every selected gap cell with overlapping patches (see cell_scan_points).
    targets = []
    seen_coords = set()

    for c in cands:
        for q_name, q_lat, q_lon in cell_scan_points(int(c["grid_x"]), int(c["grid_y"])):
            key = (round(q_lat, 5), round(q_lon, 5))
            if key not in seen_coords:
                seen_coords.add(key)
                targets.append(
                    {
                        "grid_x": c["grid_x"],
                        "grid_y": c["grid_y"],
                        "lat": q_lat,
                        "lon": q_lon,
                        "urgency": c["urgency"],
                        "road_m": c["road_m"],
                        "region_code": c["region_code"],
                        "region_name": c["region_name"],
                        "quadrant": q_name,
                    }
                )

    if limit > 0 and len(targets) > limit:
        targets = targets[:limit]

    print(
        f"   Constructed {len(targets):,} overlapping scan patches covering {len(cands):,} residential gap cells."
    )

    # 4. Multithreaded Patch Fetching
    print(f"4. Downloading Zoom-19 satellite patches for {len(targets):,} targets (Provider mode: {provider})...")
    thread_session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=24, pool_maxsize=24, max_retries=3)
    thread_session.mount("https://", adapter)
    thread_session.mount("http://", adapter)

    providers_to_fetch = ["esri", "mapbox"] if provider in ("both", "dual") else [provider]

    def fetch_job(cell: dict) -> list[tuple[dict, Image.Image]]:
        qibla_deg = round(calculate_qibla_azimuth(cell["lat"], cell["lon"]), 2)
        cell["qibla_bearing"] = qibla_deg
        items = []
        for p in providers_to_fetch:
            raw_740, rot_512 = fetch_borderless_patch(
                cell["lat"], cell["lon"], qibla_deg, thread_session, ZOOM, PATCH_SIZE, provider=p
            )
            if rot_512 is not None:
                c = dict(cell)
                c["provider"] = p
                items.append((c, rot_512))
        return items

    patches = []
    t_fetch = time.time()
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(fetch_job, t) for t in targets]
        for idx, fut in enumerate(as_completed(futures), 1):
            cell_items = fut.result()
            patches.extend(cell_items)
            if idx % 50 == 0 or idx == len(targets):
                print(f"   Fetched {idx}/{len(targets)} targets ({len(patches)} valid patches collected)...")

    print(f"   Tile acquisition completed in {time.time() - t_fetch:.1f}s.")

    # 5. Batch YOLO Inference
    print(f"5. Running YOLOv11x ({weights_path.name}) inference on {len(patches):,} patches (conf >= {conf_threshold:.2f})...")
    raw_detections = []
    t_infer = time.time()

    # Predict in chunks of 32
    batch_size = 32
    for b_idx in range(0, len(patches), batch_size):
        batch = patches[b_idx : b_idx + batch_size]
        imgs = [p[1] for p in batch]
        results = model.predict(imgs, conf=conf_threshold, verbose=False)

        for (cell, patch_img), res in zip(batch, results):
            items_to_process = []
            if hasattr(res, "obb") and res.obb is not None and len(res.obb) > 0:
                for obb in res.obb:
                    conf = float(obb.conf[0])
                    xyxy = [float(v) for v in obb.xyxy[0]]
                    xc, yc = float(obb.xywhr[0][0]), float(obb.xywhr[0][1])
                    corners = obb.xyxyxyxy[0].cpu().numpy().tolist() if hasattr(obb.xyxyxyxy[0], "cpu") else obb.xyxyxyxy[0].tolist()
                    angle_deg = math.degrees(float(obb.xywhr[0][4]))
                    items_to_process.append((conf, xyxy, xc, yc, corners, angle_deg))
            elif hasattr(res, "boxes") and res.boxes is not None and len(res.boxes) > 0:
                for box in res.boxes:
                    conf = float(box.conf[0])
                    xyxy = [float(v) for v in box.xyxy[0]]
                    xc = (xyxy[0] + xyxy[2]) / 2.0
                    yc = (xyxy[1] + xyxy[3]) / 2.0
                    items_to_process.append((conf, xyxy, xc, yc, None, 0.0))

            for conf, xyxy, xc, yc, corners, angle_deg in items_to_process:
                # Invert rotated pixel to exact geographic coordinates
                det_lat, det_lon = rotated_patch_px_to_latlon(
                    xc, yc, cell["lat"], cell["lon"], cell["qibla_bearing"], ZOOM, PATCH_SIZE
                )

                # Filter out any detection within 100m of an existing OSM mosque
                if is_near_osm_mosque(det_lat, det_lon, osm_grid, max_dist_m=100.0):
                    continue

                det_dict = {
                    "lat": det_lat,
                    "lon": det_lon,
                    "confidence": round(conf, 3),
                    "qibla_bearing": cell["qibla_bearing"],
                    "region_code": cell["region_code"],
                    "region_name": cell["region_name"],
                    "quadrant": cell.get("quadrant", "Center"),
                    "name": f"مسجد مقترح ({cell['region_code']})",
                    "source_gap_urgency": cell["urgency"],
                    "source_gap_road_m": cell["road_m"],
                    "box_xyxy": [round(v, 1) for v in xyxy],
                    "patch_img": patch_img,
                    "provider": cell.get("provider", "esri"),
                }
                if corners is not None:
                    det_dict["rotated_corners"] = [[round(p[0], 1), round(p[1], 1)] for p in corners]
                    det_dict["roof_angle_deg"] = round(angle_deg, 1)

                raw_detections.append(det_dict)

    print(
        f"   Inference finished in {time.time() - t_infer:.1f}s! "
        f"Found {len(raw_detections):,} candidate mosque detections."
    )

    # 6. Geographic Non-Maximum Suppression (Deduplication within 60m)
    print("6. Applying Geographic Non-Maximum Suppression (60m deduplication)...")
    final_detections = apply_geographic_nms(raw_detections, min_distance_m=60.0)
    print(f"   Retained {len(final_detections):,} unique, deduplicated unmapped mosque detections.")

    # 7. Export GeoJSON
    geojson_features = []
    for idx, d in enumerate(final_detections, 1):
        det_id = f"ai_det_{idx:04d}"
        osm_id_url = f"https://www.openstreetmap.org/edit?editor=id#map=19/{d['lat']}/{d['lon']}"
        josm_url = (
            f"http://127.0.0.1:8111/load_and_zoom?left={d['lon'] - 0.0015}&bottom={d['lat'] - 0.0015}"
            f"&right={d['lon'] + 0.0015}&top={d['lat'] + 0.0015}"
        )
        geojson_features.append(
            {
                "type": "Feature",
                "properties": {
                    "detection_id": det_id,
                    "name": f"مسجد مقترح بالذكاء الاصطناعي ({det_id})",
                    "confidence": d["confidence"],
                    "discovery_source": "Manara AI Autonomous Vision (100% Independent)",
                    "region_code": d["region_code"],
                    "region_name": d["region_name"],
                    "quadrant": d.get("quadrant", "Center"),
                    "qibla_bearing": d["qibla_bearing"],
                    "gap_urgency": d["source_gap_urgency"],
                    "gap_road_length_m": d["source_gap_road_m"],
                    "imagery_provider": d.get("provider_label", d.get("provider", "esri").title()),
                    "cross_verified": d.get("cross_verified", False),
                    "model_weights": weights_path.name,
                    "osm_id_editor_url": osm_id_url,
                    "josm_editor_url": josm_url,
                },
                "geometry": {"type": "Point", "coordinates": [d["lon"], d["lat"]]},
            }
        )

    geojson_payload = {
        "type": "FeatureCollection",
        "metadata": {
            "model": "YOLOv11x",
            "weights": weights_path.name,
            "conf_threshold": conf_threshold,
            "scanned_targets": len(patches),
            "detected_mosques": len(final_detections),
            "source": "Autonomous 4-Quadrant Satellite Vision Scanner (Manara AI)",
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        },
        "features": geojson_features,
    }
    output_geojson.write_text(json.dumps(geojson_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"   GeoJSON exported to: {output_geojson} ({output_geojson.stat().st_size / 1024:.1f} KB)")

    # 8. Export Visual HTML Report
    print(f"7. Rendering visual verification report to {output_html.name}...")
    cards_html = []
    # Showcase top detections in HTML grid (up to 120)
    for d in final_detections[:120]:
        ann_img = annotate_detection(d["patch_img"], d["box_xyxy"], d["confidence"], d["qibla_bearing"])
        b64 = pil_to_base64(ann_img, 360)
        prov_lbl = d.get("provider_label", "Esri World Imagery")
        prov_cls = "badge-dual" if d.get("cross_verified") else "badge-prov"
        osm_url = f"https://www.openstreetmap.org/edit?editor=id#map=19/{d['lat']}/{d['lon']}"
        quad_str = f" · {d.get('quadrant', '')} Sector" if d.get("quadrant") else ""

        cards_html.append(
            f"""
            <div class="card">
              <div class="card-header">
                <div>
                  <h3>مسجد غير مرسوم <span class="sub">({d['region_name']}{quad_str} · {d['region_code']})</span></h3>
                  <p class="meta">📍 {d['lat']:.5f}, {d['lon']:.5f} · Qibla: <b>{d['qibla_bearing']}°</b> · Gap Urgency: <b>{d['source_gap_urgency']}</b></p>
                </div>
                <div class="conf-badge">{int(d['confidence'] * 100)}% Match</div>
              </div>
              <img src="{b64}" alt="AI Detection" />
              <div class="card-footer">
                <div>
                  <span class="badge badge-new">AI Autonomous Discovery</span>
                  <span class="badge {prov_cls}">{prov_lbl}</span>
                </div>
                <a href="{osm_url}" target="_blank" class="osm-btn">🗺️ Open in iD Editor</a>
              </div>
            </div>
            """
        )

    dual_count = sum(1 for d in final_detections if d.get("cross_verified"))
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Manara AI — Autonomous Satellite Mosque Gap Scanner Results (Zero External Dependencies)</title>
  <style>
    body {{ font-family: system-ui, -apple-system, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 32px; }}
    .container {{ max-width: 1280px; margin: 0 auto; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; }}
    .subhead {{ color: #94a3b8; margin-bottom: 24px; font-size: 15px; }}
    .stats-bar {{ display: flex; gap: 16px; margin-bottom: 28px; flex-wrap: wrap; }}
    .stat-box {{ background: #1e293b; border: 1px solid #334155; padding: 16px 20px; border-radius: 12px; flex: 1; min-width: 180px; }}
    .stat-val {{ font-size: 26px; font-weight: 700; color: #38bdf8; }}
    .stat-lbl {{ font-size: 13px; color: #94a3b8; margin-top: 4px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 20px; }}
    .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 14px; overflow: hidden; }}
    .card-header {{ padding: 14px 16px; display: flex; justify-content: space-between; align-items: flex-start; }}
    .card-header h3 {{ margin: 0; font-size: 16px; }}
    .sub {{ color: #38bdf8; font-size: 13px; }}
    .meta {{ margin: 4px 0 0; font-size: 12px; color: #94a3b8; }}
    .conf-badge {{ background: #10b981; color: #0f172a; font-weight: 700; padding: 4px 8px; border-radius: 8px; font-size: 13px; }}
    .card img {{ width: 100%; display: block; border-top: 1px solid #334155; border-bottom: 1px solid #334155; }}
    .card-footer {{ padding: 12px 16px; display: flex; justify-content: space-between; align-items: center; background: #131d31; gap: 8px; }}
    .badge {{ font-size: 11px; font-weight: 700; padding: 4px 8px; border-radius: 999px; display: inline-block; margin-right: 4px; margin-bottom: 2px; }}
    .badge-new {{ background: rgba(16, 185, 129, 0.16); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.4); }}
    .badge-prov {{ background: rgba(148, 163, 184, 0.16); color: #cbd5e1; border: 1px solid rgba(148, 163, 184, 0.4); }}
    .badge-dual {{ background: rgba(234, 179, 8, 0.18); color: #fde047; border: 1px solid rgba(234, 179, 8, 0.5); }}
    .osm-btn {{ background: #2563eb; color: #fff; text-decoration: none; padding: 5px 10px; border-radius: 6px; font-size: 12px; font-weight: 600; white-space: nowrap; }}
    .osm-btn:hover {{ background: #1d4ed8; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>🛰️ Manara AI — Autonomous Satellite Mosque Gap Scanner Results (Zero External Dependencies)</h1>
    <p class="subhead">
      Autonomous computer vision scan of high-urgency residential coverage gaps from <code>worship_gaps_sa.csv</code> using boosted <b>YOLOv11x v2</b> (Weights: <code>{weights_path.name}</code>).
      Imagery Providers: <b>Esri World Imagery + Mapbox Satellite</b>.
      All detections strictly excluded from existing OSM mosques (&gt; 100m) and deduplicated (60m NMS). <b>100% Independent — Zero university/third-party priors.</b>
    </p>
    <div class="stats-bar">
      <div class="stat-box"><div class="stat-val">{len(patches):,}</div><div class="stat-lbl">Satellite Patches Evaluated</div></div>
      <div class="stat-box"><div class="stat-val">{len(final_detections):,}</div><div class="stat-lbl">Unmapped Mosques Discovered</div></div>
      <div class="stat-box"><div class="stat-val">{dual_count:,}</div><div class="stat-lbl">🌟 Dual-Confirmed (Esri + Mapbox)</div></div>
      <div class="stat-box"><div class="stat-val">{len(cands):,}</div><div class="stat-lbl">Pure Residential Gap Cells Scanned</div></div>
    </div>
    <div class="grid">
      {''.join(cards_html)}
    </div>
  </div>
</body>
</html>
"""
    output_html.write_text(html, encoding="utf-8")
    print(f"   Visual HTML Report saved to: {output_html}")
    print(f"\nDone in {(time.time() - t0):.1f}s!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scan worship coverage gaps with YOLOv11 (4-Quadrant Sub-Grid)")
    parser.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS, help="Path to best_v2.pt")
    parser.add_argument("--conf", type=float, default=0.35, help="Confidence threshold")
    parser.add_argument(
        "--cells",
        type=int,
        default=75,
        help="Number of 1km residential gap cells to survey (each cell gets 4 quadrant sub-patches)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max total quadrant patches to scan (0 = cells * 4)",
    )
    parser.add_argument("--min-urgency", type=float, default=75.0, help="Minimum urgency score")
    parser.add_argument("--min-road", type=float, default=1200.0, help="Minimum road length in meters")
    parser.add_argument("--max-road", type=float, default=12000.0, help="Maximum road length in meters")
    parser.add_argument("--region", type=str, default=None, help="Filter by region (e.g. SA-01)")
    parser.add_argument(
        "--provider",
        choices=["esri", "mapbox", "both", "dual"],
        default="both",
        help="Satellite imagery provider (default: 'both' for dual Esri + Mapbox cross-verification)",
    )
    args = parser.parse_args()

    effective_limit = args.limit if args.limit > 0 else (args.cells * 4)

    scan_gaps(
        weights_path=args.weights,
        conf_threshold=args.conf,
        limit=effective_limit,
        min_urgency=args.min_urgency,
        min_road_m=args.min_road,
        max_road_m=args.max_road,
        region_filter=args.region,
        provider=args.provider,
    )
