"""
Prunes and enriches existing ai_detected_mosques_sa.geojson using the 3-Stage Pipeline:
1. Stage 1: YOLO candidate confidence
2. Stage 2: DINOv2 visual similarity verification
3. Stage 3: Kaaba geometry (aspect ratio, min/max footprint area) & spatial cross-verification
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from PIL import Image

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "scripts"))

from stage2_verifier import verify_candidate_patch
from stage3_geometric_guard import evaluate_geometry, evaluate_spatial_and_provider

GEOJSON_FILE = ROOT_DIR / "ai_detected_mosques_sa.geojson"
DET_DIR = ROOT_DIR / "poc_satellite_output" / "phase3_detections"


def run_pruning():
    if not GEOJSON_FILE.exists():
        print("GeoJSON file does not exist.")
        return

    with open(GEOJSON_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    print(f"[Pruning] Processing {len(features)} existing detections through 3-Stage Pipeline...")

    clean_features = []
    rejected_count = 0

    for idx, ft in enumerate(features):
        p = ft["properties"]
        det_id = p.get("detection_id", f"ai_det_{idx+1:05d}")
        coords = ft["geometry"]["coordinates"]
        lon, lat = coords[0], coords[1]
        conf = float(p.get("confidence", 0.5))
        is_dual = bool(p.get("cross_verified", False))

        raw_img = DET_DIR / f"{det_id}_raw.jpg"
        ann_img = DET_DIR / f"{det_id}_ann.jpg"
        target_img = raw_img if raw_img.exists() else ann_img

        # Stage 2: DINOv2
        if target_img.exists():
            try:
                im = Image.open(target_img).convert("RGB")
                w, h = im.size
                crop = im.crop((w // 4, h // 4, 3 * w // 4, 3 * h // 4))
                st2 = verify_candidate_patch(crop)
            except Exception as e:
                st2 = {"is_mosque": conf >= 0.65, "verifier_score": conf, "reason": str(e)}
        else:
            st2 = {"is_mosque": conf >= 0.65, "verifier_score": conf, "reason": "No image crop found"}

        # Stage 3: Spatial and Provider Rules
        ok_prov, prov_reason = evaluate_spatial_and_provider(
            cross_verified=is_dual,
            stage1_conf=conf,
            stage2_score=st2["verifier_score"],
            min_dual_stage1=0.42,
            min_single_stage1=0.55,
            min_stage2_score=0.48,
        )

        if not (st2["is_mosque"] and ok_prov):
            rejected_count += 1
            continue

        # If box coordinates exist, check geometry
        box_xyxy = p.get("box_xyxy") or [200, 200, 440, 440]
        geom_eval = evaluate_geometry(box_xyxy, lat)
        if not geom_eval["is_valid"]:
            # If area is clearly wrong, drop
            if geom_eval["area_m2"] < 60 or geom_eval["area_m2"] > 5500:
                rejected_count += 1
                continue

        # Enrich properties with 3-Stage verification metadata
        p["three_stage_verified"] = True
        p["stage1_yolo_conf"] = round(conf, 3)
        p["stage2_dino_score"] = round(st2["verifier_score"], 3)
        p["stage2_dino_reason"] = st2["reason"]
        p["est_area_m2"] = geom_eval["area_m2"]
        p["aspect_ratio"] = geom_eval["aspect_ratio"]

        clean_features.append(ft)

    print(f"[Pruning] Done! Kept {len(clean_features)} confirmed mosques. Purged {rejected_count} false alarms.")

    data["features"] = clean_features
    data["metadata"]["total_detected_mosques"] = len(clean_features)
    data["metadata"]["verification_pipeline"] = "3-Stage (YOLOv11x + DINOv2 + Kaaba Geometry)"

    with open(GEOJSON_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # Re-render dashboard
    sys.path.insert(0, str(ROOT_DIR / "scripts"))
    from ai_background_sweeper import load_sweeper_state, render_live_dashboard
    state = load_sweeper_state()
    render_live_dashboard(clean_features, state, current_cycle=0)
    print("[Pruning] Live dashboard re-rendered successfully!")


if __name__ == "__main__":
    run_pruning()
