"""
Re-annotates all verified detections in ai_detected_mosques_sa.geojson
using Level 1 Roof-Boundary Snapping, updating thumbnail crops and re-rendering
sweeper_live_dashboard.html.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from PIL import Image

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "scripts"))

from roof_boundary_snapping import snap_roof_boundary, draw_snapped_annotation
from scan_worship_gaps import pil_to_base64
from ai_background_sweeper import load_sweeper_state, render_live_dashboard

GEOJSON_FILE = ROOT_DIR / "ai_detected_mosques_sa.geojson"
OUTPUT_DIR = ROOT_DIR / "poc_satellite_output"
DET_DIR = OUTPUT_DIR / "phase3_detections"


def reannotate():
    if not GEOJSON_FILE.exists():
        print("No GeoJSON file found.")
        return

    with open(GEOJSON_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    print(f"[Reannotate] Snapping roof boundaries for {len(features)} verified mosques...")

    updated_count = 0
    for ft in features:
        p = ft["properties"]
        det_id = p.get("detection_id")
        lat = ft["geometry"]["coordinates"][1]
        conf = float(p.get("confidence", 0.6))
        qibla = float(p.get("qibla_bearing", 0.0))
        dino_score = float(p.get("stage2_dino_score", conf))

        raw_path = DET_DIR / f"{det_id}_raw.jpg"
        ann_path = DET_DIR / f"{det_id}_ann.jpg"
        img_path = raw_path if raw_path.exists() else ann_path

        if not img_path.exists():
            continue

        try:
            im = Image.open(img_path).convert("RGB")
            # If box_xyxy is known or estimate from center
            w, h = im.size
            box_xyxy = p.get("box_xyxy")
            if not box_xyxy:
                # Center 45% box
                box_xyxy = [w * 0.28, h * 0.28, w * 0.72, h * 0.72]

            snap_res = snap_roof_boundary(im, box_xyxy, lat=lat, zoom=19)
            annotated = draw_snapped_annotation(
                patch_512=im,
                corners=snap_res["rotated_corners"],
                conf=conf,
                qibla_bearing=qibla,
                dino_score=dino_score,
                area_m2=snap_res["area_m2"],
            )

            annotated.save(ann_path, quality=90)
            p["thumbnail"] = pil_to_base64(annotated, max_side=340)
            p["est_area_m2"] = snap_res["area_m2"]
            p["aspect_ratio"] = snap_res["aspect_ratio"]
            p["roof_angle_deg"] = snap_res["roof_angle_deg"]
            p["rotated_corners"] = snap_res["rotated_corners"]
            p["snapped_roof"] = snap_res["snapped"]
            updated_count += 1
        except Exception as e:
            print(f"  Note on {det_id}: {e}")

    with open(GEOJSON_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"[Reannotate] Successfully snapped and updated {updated_count} mosques!")

    state = load_sweeper_state()
    render_live_dashboard(features, state, current_cycle=0)
    print("[Reannotate] Live dashboard re-rendered with tight aligned roof boundaries!")


if __name__ == "__main__":
    reannotate()
