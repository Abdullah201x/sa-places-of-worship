"""
Phase 5 Dataset Booster: Expand Mosque Dataset v2 to 3,500 Patches
==================================================================
Boosts `mosque_dataset_v2` from 2,045 patches up to 3,500 patches:
- 1,100+ fresh verified positive mosques sampled from unused OSM polygons and regional KAUST records
  (heavy weighting on 'Asir, Jazan, Al-Bahah, Najran, Tabuk, Al Jawf, and complex urban footprints).
- 350+ fresh hard negative background patches (terrain, desert, non-mosque residential grids).
- Target distribution: Exactly 2,800 train (80%) and 700 val (20%).
- Multithreaded acquisition (16 workers) with local tile caching.
- Direct packaging into `poc_satellite_output/mosque_dataset_v2.zip`.
"""

from __future__ import annotations

import argparse
import collections
import io
import json
import math
import os
import random
import shutil
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import requests
from PIL import Image
from shapely.geometry import Point, shape
from shapely.prepared import prep

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

OUTPUT_DIR = ROOT_DIR / "poc_satellite_output"
DATASET_V2_DIR = OUTPUT_DIR / "mosque_dataset_v2"
DATASET_V2_ZIP = OUTPUT_DIR / "mosque_dataset_v2.zip"
OSM_WAY_BBOXES = OUTPUT_DIR / "step1_1_bboxes" / "osm_way_bboxes.jsonl"
KAUST_BBOXES = OUTPUT_DIR / "step1_1_bboxes" / "kaust_regional_1300_bboxes.jsonl"
REGIONS_GEOJSON = ROOT_DIR / "sa_regions.geojson"
MOSQUES_GEOJSON = ROOT_DIR / "places_of_worship_sa.geojson"

TARGET_TRAIN = 2800
TARGET_VAL = 700
TARGET_TOTAL = TARGET_TRAIN + TARGET_VAL
OUTER_HALF = 370


def fetch_borderless_patch(
    lat: float,
    lon: float,
    qibla_bearing: float,
    session: requests.Session,
    zoom: int = ZOOM,
    patch_size: int = PATCH_SIZE,
    provider: str = "esri",
) -> Image.Image | None:
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
        return None

    rot_740 = crop_740.rotate(qibla_bearing, resample=Image.Resampling.BICUBIC, expand=False)
    margin = OUTER_HALF - (patch_size // 2)
    return rot_740.crop((margin, margin, margin + patch_size, margin + patch_size))


def boost_dataset(provider: str = "esri") -> None:
    t0 = time.time()
    print("=" * 78)
    print(f"BOOSTING DATASET V2 TO EXACTLY 3,500 TOTAL SAMPLES (Provider: {provider})")
    print("=" * 78)

    train_img_dir = DATASET_V2_DIR / "train" / "images"
    train_lbl_dir = DATASET_V2_DIR / "train" / "labels"
    val_img_dir = DATASET_V2_DIR / "val" / "images"
    val_lbl_dir = DATASET_V2_DIR / "val" / "labels"

    for d in [train_img_dir, train_lbl_dir, val_img_dir, val_lbl_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # 1. Inspect existing dataset
    existing_train = set(f.stem for f in train_img_dir.glob("*.jpg"))
    existing_val = set(f.stem for f in val_img_dir.glob("*.jpg"))
    existing_ids = existing_train | existing_val

    needed_train = max(0, TARGET_TRAIN - len(existing_train))
    needed_val = max(0, TARGET_VAL - len(existing_val))
    total_needed = needed_train + needed_val

    print(f"1. Current dataset status:")
    print(f"   - Train: {len(existing_train):,} / {TARGET_TRAIN:,} (needs {needed_train:,})")
    print(f"   - Val:   {len(existing_val):,} / {TARGET_VAL:,} (needs {needed_val:,})")
    print(f"   - Total: {len(existing_ids):,} / {TARGET_TOTAL:,} (needs {total_needed:,})")

    if total_needed <= 0:
        print(f"   Dataset already has {len(existing_ids):,} patches (>= {TARGET_TOTAL:,}). Nothing to boost!")
        return

    # 2. Select Unused Verified Mosques
    print("\n2. Selecting fresh, verified mosques across all 13 provinces...")
    osm_lines = [json.loads(l) for l in OSM_WAY_BBOXES.read_text(encoding="utf-8").splitlines() if l.strip()]
    kaust_lines = [json.loads(l) for l in KAUST_BBOXES.read_text(encoding="utf-8").splitlines() if l.strip()]

    unused_osm = [r for r in osm_lines if r["id"] not in existing_ids]
    unused_kaust = [r for r in kaust_lines if r["id"] not in existing_ids]

    print(f"   Available candidate pool: {len(unused_osm):,} unused OSM polygons + {len(unused_kaust):,} unused KAUST records.")

    # Target: 76% positive mosques + 24% hard negatives
    # We buffer by +20% candidates in case of any placeholder tiles in remote regions
    target_positives = int(total_needed * 0.76) + 150
    target_negatives = (total_needed - int(total_needed * 0.76)) + 80

    by_region: dict[str, list[dict]] = collections.defaultdict(list)
    for r in unused_kaust:
        by_region[r.get("region_code", "SA-XX")].append(r)
    for r in unused_osm:
        by_region[r.get("region_code", "SA-XX")].append(r)

    selected_positives: list[dict] = []
    reg_keys = sorted(by_region.keys())
    idx = 0
    while len(selected_positives) < target_positives:
        added_any = False
        for k in reg_keys:
            if idx < len(by_region[k]):
                selected_positives.append(by_region[k][idx])
                added_any = True
                if len(selected_positives) >= target_positives:
                    break
        if not added_any:
            break
        idx += 1

    print(f"   Selected {len(selected_positives):,} diverse positive mosques across {len(reg_keys)} regions.")

    # 3. Generate Fresh Hard Negatives
    print(f"\n3. Generating {target_negatives:,} diverse hard negative background patches...")
    regions_fc = json.loads(REGIONS_GEOJSON.read_text(encoding="utf-8"))
    regions_shapes = [prep(shape(f["geometry"])) for f in regions_fc["features"]]

    mosques_fc = json.loads(MOSQUES_GEOJSON.read_text(encoding="utf-8"))
    mosque_grid: dict[tuple[int, int], list[tuple[float, float]]] = collections.defaultdict(list)
    for f in mosques_fc["features"]:
        lon, lat = f["geometry"]["coordinates"]
        gx, gy = int(lon / 0.005), int(lat / 0.005)
        mosque_grid[(gx, gy)].append((lat, lon))

    def is_far_from_any_mosque(lat: float, lon: float, min_m: float = 350.0) -> bool:
        gx, gy = int(lon / 0.005), int(lat / 0.005)
        m_lat = 110_574.0
        m_lon = 111_320.0 * math.cos(math.radians(lat))
        r2 = min_m * min_m
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for mlat, mlon in mosque_grid.get((gx + dx, gy + dy), ()):
                    dy_m = (lat - mlat) * m_lat
                    dx_m = (lon - mlon) * m_lon
                    if dx_m * dx_m + dy_m * dy_m <= r2:
                        return False
        return True

    rng = random.Random(42)
    selected_negatives: list[dict] = []
    anchor_points = [
        (18.216, 42.505),  # Asir mountain terrace
        (18.250, 42.480),
        (16.889, 42.551),  # Jazan coastal & foothills
        (17.050, 42.950),
        (20.012, 41.467),  # Al-Bahah escarpment
        (19.850, 41.350),
        (24.850, 46.550),  # Riyadh outer desert & highway
        (24.520, 46.900),
        (26.350, 43.950),  # Qassim plains
        (28.400, 36.550),  # Tabuk desert mountains
        (26.300, 50.150),  # Eastern Province industrial
        (27.050, 49.600),
        (30.000, 40.200),  # Al Jawf rocky terrain
        (17.500, 44.150),  # Najran border foothills
    ]

    while len(selected_negatives) < target_negatives:
        anchor_lat, anchor_lon = rng.choice(anchor_points)
        d_lat = rng.uniform(-0.25, 0.25)
        d_lon = rng.uniform(-0.25, 0.25)
        lat = round(anchor_lat + d_lat, 6)
        lon = round(anchor_lon + d_lon, 6)

        pt = Point(lon, lat)
        in_sa = any(pgeom.contains(pt) for pgeom in regions_shapes)
        if not in_sa:
            continue

        if is_far_from_any_mosque(lat, lon, min_m=350.0):
            neg_id = f"boost_neg_{len(existing_ids) + len(selected_negatives) + 1:05d}"
            qibla = round(calculate_qibla_azimuth(lat, lon), 2)
            selected_negatives.append(
                {
                    "id": neg_id,
                    "lat": lat,
                    "lon": lon,
                    "qibla_bearing": qibla,
                    "is_negative": True,
                }
            )

    print(f"   Generated {len(selected_negatives):,} verified hard negative locations.")

    # 4. Prepare Jobs
    all_jobs = []
    for pos in selected_positives:
        all_jobs.append(
            {
                "id": pos["id"],
                "lat": pos["lat"],
                "lon": pos["lon"],
                "qibla_bearing": pos["qibla_bearing"],
                "yolo_line": pos["bbox_data"]["qibla_yolo_line"],
                "is_negative": False,
            }
        )
    for neg in selected_negatives:
        all_jobs.append(
            {
                "id": neg["id"],
                "lat": neg["lat"],
                "lon": neg["lon"],
                "qibla_bearing": neg["qibla_bearing"],
                "yolo_line": "",
                "is_negative": True,
            }
        )

    rng.shuffle(all_jobs)

    print(f"\n4. Downloading and rendering satellite patches (16 threads, target additions: {total_needed:,})...")
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=32, pool_maxsize=32, max_retries=3)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    def fetch_job(job: dict) -> tuple[dict, Image.Image | None]:
        patch = fetch_borderless_patch(job["lat"], job["lon"], job["qibla_bearing"], session, ZOOM, PATCH_SIZE, provider=provider)
        return job, patch

    cur_train = len(list(train_img_dir.glob("*.jpg")))
    cur_val = len(list(val_img_dir.glob("*.jpg")))

    saved_pos = 0
    saved_neg = 0

    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(fetch_job, j) for j in all_jobs]
        for idx, fut in enumerate(as_completed(futures), 1):
            if cur_train >= TARGET_TRAIN and cur_val >= TARGET_VAL:
                print(f"   Both train ({cur_train}) and val ({cur_val}) targets reached! Stopping.")
                break

            try:
                job, patch = fut.result()
            except Exception:
                continue

            if patch is None:
                continue

            # Determine split assignment:
            # Need TARGET_TRAIN and TARGET_VAL
            if cur_train < TARGET_TRAIN and cur_val < TARGET_VAL:
                # 80% train, 20% val
                is_val = (random.random() < 0.20)
            elif cur_val < TARGET_VAL:
                is_val = True
            elif cur_train < TARGET_TRAIN:
                is_val = False
            else:
                break

            target_img_dir = val_img_dir if is_val else train_img_dir
            target_lbl_dir = val_lbl_dir if is_val else train_lbl_dir

            img_path = target_img_dir / f"{job['id']}.jpg"
            lbl_path = target_lbl_dir / f"{job['id']}.txt"

            patch.save(img_path, format="JPEG", quality=93)
            lbl_content = (job["yolo_line"] + "\n") if not job["is_negative"] else ""
            lbl_path.write_text(lbl_content, encoding="utf-8")

            if is_val:
                cur_val += 1
            else:
                cur_train += 1

            if job["is_negative"]:
                saved_neg += 1
            else:
                saved_pos += 1

            total_saved = (cur_train - len(existing_train)) + (cur_val - len(existing_val))
            if total_saved % 100 == 0 or (cur_train >= TARGET_TRAIN and cur_val >= TARGET_VAL):
                print(
                    f"   Progress: {cur_train + cur_val}/{TARGET_TOTAL} "
                    f"[Train: {cur_train}/{TARGET_TRAIN}, Val: {cur_val}/{TARGET_VAL}] "
                    f"(+{saved_pos} mosques, +{saved_neg} hard negatives)"
                )

    final_train = len(list(train_img_dir.glob("*.jpg")))
    final_val = len(list(val_img_dir.glob("*.jpg")))
    final_total = final_train + final_val
    print(f"\n5. Boosted Dataset Size:")
    print(f"   - Train: {final_train:,} images + labels")
    print(f"   - Val:   {final_val:,} images + labels")
    print(f"   - Total: {final_total:,} patches (Exactly {final_train/final_total*100:.1f}% / {final_val/final_total*100:.1f}% split)")

    # Update dataset.yaml with portable path
    yaml_path = DATASET_V2_DIR / "dataset.yaml"
    yaml_content = (
        "# YOLOv11 Mosque Detector — Dataset v2 (Active Learning Boosted 3,500 Edition)\n"
        "path: .\n"
        "train: train/images\n"
        "val: val/images\n\n"
        "nc: 1\n"
        "names: ['mosque']\n"
    )
    yaml_path.write_text(yaml_content, encoding="utf-8")
    print(f"   Updated {yaml_path.name} with portable paths.")

    # 5. Re-archive mosque_dataset_v2.zip
    print(f"\n6. Compressing full boosted dataset to {DATASET_V2_ZIP.name}...")
    with zipfile.ZipFile(DATASET_V2_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in DATASET_V2_DIR.rglob("*"):
            if f.is_file():
                arcname = f.relative_to(DATASET_V2_DIR)
                zf.write(f, arcname)

    size_mb = DATASET_V2_ZIP.stat().st_size / (1024 * 1024)
    print(f"   Boosted dataset package ready: {DATASET_V2_ZIP} ({size_mb:.1f} MB)")
    print(f"Done in {time.time() - t0:.1f}s!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Boost dataset v2 to 3,500 samples")
    parser.add_argument("--provider", choices=["esri", "mapbox"], default="esri", help="Satellite imagery provider")
    args = parser.parse_args()
    boost_dataset(provider=args.provider)

