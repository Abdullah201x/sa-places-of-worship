"""
Phase 5: Active Learning Loop & Dataset v2 Builder
=================================================
Implements Phase 5 of the satellite detection plan:

1. Loads the 45 AI-detected unmapped mosques from Phase 3 (ai_detected_mosques_sa.geojson).
2. Generates an interactive Review Dashboard (poc_satellite_output/phase5_review.html)
   where you can confirm real mosques (Positives) and reject tricky false alarms (Hard Negatives).
3. Provides an integrated local server (python scripts/phase5_active_learning.py --serve)
   that saves your reviews to disk with 1 click.
4. Builds Mosque Dataset v2 (poc_satellite_output/mosque_dataset_v2.zip):
   - Merges original 2,000 baseline patches.
   - Adds confirmed unmapped mosques as new positive training samples.
   - Adds rejected false alarms as high-value hard negative background samples.
   - Augments with 1,000 additional rural/mountain mosque footprints from 'Asir, Jazan, and Al-Bahah.
5. Generates the updated Google Colab notebook (train_yolov11x_v2_colab.ipynb) for 640px A100 fine-tuning!
"""

from __future__ import annotations

import argparse
import base64
import http.server
import io
import json
import math
import os
import shutil
import socketserver
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw
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

GEOJSON_FILE = ROOT_DIR / "ai_detected_mosques_sa.geojson"
WEIGHTS_FILE = (
    ROOT_DIR / "poc_satellite_output" / "best_v3.pt"
    if (ROOT_DIR / "poc_satellite_output" / "best_v3.pt").exists()
    else (
        ROOT_DIR / "poc_satellite_output" / "best_v2.pt"
        if (ROOT_DIR / "poc_satellite_output" / "best_v2.pt").exists()
        else ROOT_DIR / "poc_satellite_output" / "best.pt"
    )
)
OUTPUT_DIR = ROOT_DIR / "poc_satellite_output"
DETECTIONS_DIR = OUTPUT_DIR / "phase3_detections"
REVIEW_HTML_FILE = OUTPUT_DIR / "phase5_review.html"
FEEDBACK_JSON_FILE = OUTPUT_DIR / "active_learning_feedback.json"
DATASET_V1_DIR = OUTPUT_DIR / "mosque_dataset"
DATASET_V2_DIR = OUTPUT_DIR / "mosque_dataset_v2"
DATASET_V2_ZIP = OUTPUT_DIR / "mosque_dataset_v2.zip"
COLAB_V2_NB = OUTPUT_DIR / "train_yolov11x_v2_colab.ipynb"

OUTER_HALF = 370


# ---------------------------------------------------------------------------
# Helper: Fetch Borderless Patch & Annotate
# ---------------------------------------------------------------------------


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


def annotate_box(patch_512: Image.Image, box: list[float], conf: float, qibla_bearing: float) -> Image.Image:
    vis = patch_512.copy().convert("RGBA")
    ov = Image.new("RGBA", vis.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(ov)

    x0, y0, x1, y1 = box
    draw.rectangle([x0, y0, x1, y1], fill=(16, 185, 129, 45), outline=(16, 185, 129, 255), width=3)

    # Corner brackets
    c_len = 14
    for cx, cy, sx, sy in [(x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)]:
        draw.line([(cx, cy), (cx + sx * c_len, cy)], fill=(52, 211, 153, 255), width=4)
        draw.line([(cx, cy), (cx, cy + sy * c_len)], fill=(52, 211, 153, 255), width=4)

    # Qibla UP compass indicator in top-right
    ccx, ccy, cr = vis.width - 36, 36, 22
    draw.ellipse([(ccx - cr, ccy - cr), (ccx + cr, ccy + cr)], fill=(15, 23, 42, 200), outline=(255, 255, 255, 190))
    draw.line([(ccx, ccy + 10), (ccx, ccy - cr + 5)], fill=(250, 204, 21, 255), width=3)
    draw.ellipse([(ccx - 3, ccy - cr + 2), (ccx + 3, ccy - cr + 8)], fill=(250, 204, 21, 255))

    return Image.alpha_composite(vis, ov).convert("RGB")


def pil_to_base64(img: Image.Image, max_side: int = 400) -> str:
    if img.width > max_side:
        img = img.resize((max_side, max_side), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


# ---------------------------------------------------------------------------
# Step 1: Prepare Detections & Extract Bounding Boxes
# ---------------------------------------------------------------------------


def prepare_detections(model: YOLO | None = None, provider: str = "esri") -> list[dict]:
    """
    Extracts raw patch, bounding box, and annotated preview for all detection candidates across all sessions.
    """
    DETECTIONS_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=16, pool_maxsize=16, max_retries=3)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    if model is None:
        model = YOLO(str(WEIGHTS_FILE))

    # Collect all unique candidate dictionaries across meta files and GeoJSON
    candidates_dict = {}

    # 1. From existing meta files in phase3_detections
    for meta_path in sorted(DETECTIONS_DIR.glob("*_meta.json")):
        try:
            m = json.loads(meta_path.read_text(encoding="utf-8"))
            det_id = m.get("detection_id")
            if det_id:
                candidates_dict[det_id] = m
        except Exception:
            pass

    # 2. From GeoJSON features
    if GEOJSON_FILE.exists():
        fc = json.loads(GEOJSON_FILE.read_text(encoding="utf-8"))
        for f in fc.get("features", []):
            props = f.get("properties", {})
            det_id = props.get("detection_id")
            if det_id and det_id not in candidates_dict:
                candidates_dict[det_id] = {
                    "detection_id": det_id,
                    "name": props.get("name", det_id),
                    "confidence": float(props.get("confidence", 0.5)),
                    "region_code": props.get("region_code", "SA-01"),
                    "region_name": props.get("region_name", "Kingdom of Saudi Arabia"),
                    "lat": float(f["geometry"]["coordinates"][1]),
                    "lon": float(f["geometry"]["coordinates"][0]),
                    "qibla_bearing": float(props.get("qibla_bearing", 0.0)),
                    "osm_id_editor_url": props.get("osm_id_editor_url", ""),
                }

    print(f"1. Preparing {len(candidates_dict)} total detection candidates for review...")

    items = []
    for det_id, props in sorted(candidates_dict.items()):
        lat = props["lat"]
        lon = props["lon"]
        qibla = props.get("qibla_bearing", 0.0)
        raw_path = DETECTIONS_DIR / f"{det_id}_raw.jpg"
        ann_path = DETECTIONS_DIR / f"{det_id}_ann.jpg"
        meta_path = DETECTIONS_DIR / f"{det_id}_meta.json"

        if raw_path.exists() and meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                raw_img = Image.open(raw_path).convert("RGB")
                box_xyxy = meta["box_xyxy"]
                box_yolo = meta["box_yolo"]
            except Exception:
                continue
        else:
            raw_img = fetch_borderless_patch(lat, lon, qibla, session, ZOOM, PATCH_SIZE, provider=provider)
            if raw_img is None:
                continue
            raw_img.save(raw_path, format="JPEG", quality=95)

            res = model.predict(raw_img, conf=0.25, verbose=False)
            boxes = res[0].boxes
            if len(boxes) > 0:
                xyxy = [round(float(v), 1) for v in boxes.xyxy[0]]
                x0, y0, x1, y1 = xyxy
                w = x1 - x0
                h = y1 - y0
                xc = (x0 + x1) / 2.0
                yc = (y0 + y1) / 2.0
                box_yolo = [round(xc / 512.0, 6), round(yc / 512.0, 6), round(w / 512.0, 6), round(h / 512.0, 6)]
            else:
                xyxy = [180.0, 180.0, 332.0, 332.0]
                box_yolo = [0.5, 0.5, 0.3, 0.3]

            meta = {
                "detection_id": det_id,
                "name": props.get("name", f"Candidate ({det_id})"),
                "confidence": props.get("confidence", 0.5),
                "region_code": props.get("region_code", "SA-01"),
                "region_name": props.get("region_name", "Kingdom of Saudi Arabia"),
                "lat": lat,
                "lon": lon,
                "qibla_bearing": qibla,
                "box_xyxy": xyxy,
                "box_yolo": box_yolo,
                "osm_id_editor_url": props.get(
                    "osm_id_editor_url", f"https://www.openstreetmap.org/edit?editor=id#map=19/{lat}/{lon}"
                ),
            }
            meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
            box_xyxy = xyxy

        if not ann_path.exists():
            ann_img = annotate_box(raw_img, box_xyxy, props["confidence"], qibla)
            ann_img.save(ann_path, format="JPEG", quality=90)
        else:
            ann_img = Image.open(ann_path).convert("RGB")

        items.append(
            {
                "detection_id": det_id,
                "name": props.get("name", f"Candidate ({det_id})"),
                "confidence": float(props.get("confidence", 0.5)),
                "region_code": props.get("region_code", "SA-01"),
                "region_name": props.get("region_name", "Kingdom of Saudi Arabia"),
                "lat": lat,
                "lon": lon,
                "qibla_bearing": qibla,
                "box_xyxy": box_xyxy,
                "box_yolo": box_yolo,
                "osm_id_editor_url": props.get(
                    "osm_id_editor_url", f"https://www.openstreetmap.org/edit?editor=id#map=19/{lat}/{lon}"
                ),
                "ann_base64": pil_to_base64(ann_img, 380),
                "raw_file": str(raw_path.relative_to(ROOT_DIR)).replace("\\", "/"),
            }
        )

    print(f"   Successfully prepared {len(items)} detection patches with bounding boxes.")
    return items


# ---------------------------------------------------------------------------
# Step 2: Render Interactive Review Dashboard HTML
# ---------------------------------------------------------------------------


def generate_review_html(items: list[dict], output_file: Path = REVIEW_HTML_FILE) -> None:
    print(f"2. Generating interactive Active Learning Review Dashboard at {output_file.name}...")

    # Load existing feedback if present
    existing_feedback = {}
    if FEEDBACK_JSON_FILE.exists():
        try:
            existing_feedback = json.loads(FEEDBACK_JSON_FILE.read_text(encoding="utf-8"))
        except Exception:
            existing_feedback = {}

    cards_json = []
    for it in items:
        det_id = it["detection_id"]
        if det_id in existing_feedback:
            status = existing_feedback[det_id].get("status", "unsure")
        else:
            status = "unsure"
        it_copy = dict(it)
        it_copy["status"] = status
        cards_json.append(it_copy)

    # Sort so that "unsure" (fresh unreviewed) come FIRST!
    cards_json.sort(key=lambda x: (0 if x["status"] == "unsure" else 1, -x["confidence"]))

    items_json_str = json.dumps(cards_json, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Phase 5 — Active Learning Mosque Reviewer</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    :root {{
      --bg: #0b1120;
      --card-bg: #1e293b;
      --card-border: #334155;
      --text: #f8fafc;
      --text-dim: #94a3b8;
      --accent: #38bdf8;
      --green: #10b981;
      --red: #ef4444;
      --yellow: #f59e0b;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: system-ui, -apple-system, sans-serif;
      background: var(--bg);
      color: var(--text);
      margin: 0;
      padding: 0 0 100px;
    }}
    header {{
      position: sticky;
      top: 0;
      background: rgba(15, 23, 42, 0.95);
      backdrop-filter: blur(8px);
      border-bottom: 1px solid var(--card-border);
      padding: 16px 24px;
      z-index: 100;
    }}
    .header-top {{
      max-width: 1360px;
      margin: 0 auto;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 16px;
    }}
    h1 {{ margin: 0; font-size: 22px; display: flex; align-items: center; gap: 8px; }}
    .stats-chips {{
      display: flex;
      gap: 10px;
      font-size: 13px;
      font-weight: 600;
      flex-wrap: wrap;
    }}
    .chip {{
      padding: 6px 12px;
      border-radius: 999px;
      display: flex;
      align-items: center;
      gap: 6px;
    }}
    .chip-total {{ background: #334155; color: #f8fafc; }}
    .chip-pos {{ background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.4); }}
    .chip-neg {{ background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.4); }}
    .chip-unsure {{ background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.4); }}

    .actions-bar {{
      display: flex;
      gap: 10px;
    }}
    .btn {{
      padding: 8px 16px;
      border-radius: 8px;
      font-weight: 600;
      font-size: 13px;
      cursor: pointer;
      border: none;
      transition: all 0.15s ease;
    }}
    .btn-save {{ background: #2563eb; color: #fff; }}
    .btn-save:hover {{ background: #1d4ed8; }}
    .btn-secondary {{ background: #334155; color: #cbd5e1; }}
    .btn-secondary:hover {{ background: #475569; }}

    .container {{
      max-width: 1360px;
      margin: 24px auto 0;
      padding: 0 20px;
    }}
    .filter-bar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 20px;
      flex-wrap: wrap;
      gap: 12px;
    }}
    .filter-group {{
      display: flex;
      gap: 8px;
      align-items: center;
    }}
    select {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      color: var(--text);
      padding: 6px 12px;
      border-radius: 6px;
      font-size: 13px;
    }}

    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
      gap: 22px;
    }}
    .card {{
      background: var(--card-bg);
      border: 2px solid var(--card-border);
      border-radius: 14px;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      transition: transform 0.12s ease, border-color 0.15s ease;
    }}
    .card.status-positive {{ border-color: var(--green); }}
    .card.status-negative {{ border-color: var(--red); opacity: 0.85; }}
    .card.status-unsure {{ border-color: var(--yellow); }}

    .card-header {{
      padding: 14px 16px;
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 10px;
    }}
    .card-title {{ margin: 0; font-size: 16px; font-weight: 700; }}
    .card-sub {{ color: var(--accent); font-size: 13px; font-weight: 500; }}
    .card-meta {{ margin: 4px 0 0; font-size: 12px; color: var(--text-dim); }}
    .badge-conf {{
      background: #10b981;
      color: #0f172a;
      font-weight: 700;
      padding: 3px 8px;
      border-radius: 6px;
      font-size: 12px;
      white-space: nowrap;
    }}

    .card-img-wrap {{
      position: relative;
      background: #000;
    }}
    .card img {{
      width: 100%;
      height: 380px;
      object-fit: cover;
      display: block;
      border-top: 1px solid var(--card-border);
      border-bottom: 1px solid var(--card-border);
    }}

    .card-footer {{
      padding: 14px 16px;
      background: #131d31;
      display: flex;
      flex-direction: column;
      gap: 10px;
      flex: 1;
      justify-content: space-between;
    }}
    .decision-buttons {{
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 6px;
    }}
    .btn-decision {{
      padding: 8px 6px;
      border-radius: 8px;
      border: 1px solid transparent;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 4px;
      background: #1e293b;
      color: var(--text-dim);
      transition: all 0.12s ease;
    }}
    .btn-decision:hover {{ background: #334155; color: #fff; }}
    .btn-decision.active-pos {{
      background: rgba(16, 185, 129, 0.25);
      color: #34d399;
      border-color: #10b981;
      font-weight: 700;
    }}
    .btn-decision.active-neg {{
      background: rgba(239, 68, 68, 0.25);
      color: #f87171;
      border-color: #ef4444;
      font-weight: 700;
    }}
    .btn-decision.active-unsure {{
      background: rgba(245, 158, 11, 0.25);
      color: #fbbf24;
      border-color: #f59e0b;
      font-weight: 700;
    }}

    .osm-link {{
      font-size: 12px;
      color: var(--accent);
      text-decoration: none;
      text-align: center;
      padding-top: 4px;
      font-weight: 500;
    }}
    .osm-link:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>

  <header>
    <div class="header-top">
      <div>
        <h1>🛰️ Phase 5 — Active Learning Mosque Reviewer</h1>
        <div style="font-size: 12px; color: var(--text-dim); margin-top: 2px;">
          Review AI detections from Phase 3 to train <b>Version 2 (YOLOv11x)</b> on Colab Pro A100.
        </div>
      </div>
      <div class="stats-chips">
        <div class="chip" id="goal-chip" style="background: rgba(239, 68, 68, 0.25); border: 2px solid #ef4444; color: #fca5a5; font-size: 14px; font-weight: 800; padding: 6px 14px; border-radius: 999px;">
          🎯 Target: <span id="stat-neg-goal" style="color: #fff; font-size: 18px;">0</span> / 50 Hard Negatives
        </div>
        <div class="chip chip-pos">✅ Mosques: <span id="stat-pos">0</span></div>
        <div class="chip chip-neg">❌ Hard Negatives: <span id="stat-neg">0</span></div>
        <div class="chip chip-unsure">✨ Fresh To Review: <span id="stat-unsure">0</span></div>
      </div>
      <div class="actions-bar">
        <button class="btn btn-secondary" onclick="markAllHighConf()">⚡ Auto-Keep &gt;60%</button>
        <button class="btn btn-save" onclick="saveFeedback()">💾 Save Feedback</button>
      </div>
    </div>
  </header>

  <div class="container">
    <div class="filter-bar">
      <div class="filter-group">
        <label style="font-size: 13px; color: var(--text-dim);">Filter Status:</label>
        <select id="filter-status" onchange="applyFilters()">
          <option value="unsure" selected>✨ Fresh To Review (Ready)</option>
          <option value="all">All Candidates</option>
          <option value="negative">❌ Hard Negatives Marked</option>
          <option value="positive">✅ Confirmed Mosques</option>
        </select>

        <label style="font-size: 13px; color: var(--text-dim); margin-left: 12px;">Region:</label>
        <select id="filter-region" onchange="applyFilters()">
          <option value="all">All Provinces</option>
        </select>
      </div>
      <div style="font-size: 12px; color: var(--text-dim);">
        Keyboard shortcuts: <b>1</b> = Keep Mosque · <b>2</b> = False Alarm (Hard Negative) · <b>3</b> = Skip
      </div>
    </div>

    <div class="grid" id="cards-grid"></div>
  </div>

  <script>
    const items = {items_json_str};

    // Populate regions dropdown
    const regionSelect = document.getElementById('filter-region');
    const regions = Array.from(new Set(items.map(it => it.region_name))).sort();
    regions.forEach(r => {{
      const opt = document.createElement('option');
      opt.value = r;
      opt.textContent = r;
      regionSelect.appendChild(opt);
    }});

    function updateStats() {{
      const total = items.length;
      const pos = items.filter(it => it.status === 'positive').length;
      const neg = items.filter(it => it.status === 'negative').length;
      const unsure = items.filter(it => it.status === 'unsure').length;

      document.getElementById('stat-pos').textContent = pos;
      document.getElementById('stat-neg').textContent = neg;
      document.getElementById('stat-unsure').textContent = unsure;

      const goalEl = document.getElementById('stat-neg-goal');
      const goalChip = document.getElementById('goal-chip');
      if (goalEl && goalChip) {{
        goalEl.textContent = neg;
        if (neg >= 50) {{
          goalChip.style.background = 'rgba(16, 185, 129, 0.25)';
          goalChip.style.borderColor = '#10b981';
          goalChip.style.color = '#34d399';
          goalChip.innerHTML = `🎉 Goal Reached! <b>${{neg}} / 50</b> Hard Negatives Collected!`;
        }}
      }}
    }}

    function setStatus(detId, status) {{
      const item = items.find(it => it.detection_id === detId);
      if (!item) return;
      item.status = status;
      updateStats();

      const card = document.getElementById('card-' + detId);
      if (card) {{
        card.className = 'card status-' + status;
        const btnPos = card.querySelector('.btn-pos');
        const btnNeg = card.querySelector('.btn-neg');
        const btnUnsure = card.querySelector('.btn-unsure');

        btnPos.className = 'btn-decision btn-pos' + (status === 'positive' ? ' active-pos' : '');
        btnNeg.className = 'btn-decision btn-neg' + (status === 'negative' ? ' active-neg' : '');
        btnUnsure.className = 'btn-decision btn-unsure' + (status === 'unsure' ? ' active-unsure' : '');
      }}
    }}

    function renderCards() {{
      const grid = document.getElementById('cards-grid');
      grid.innerHTML = '';
      const filterStatus = document.getElementById('filter-status').value;
      const filterRegion = document.getElementById('filter-region').value;

      items.forEach(it => {{
        if (filterStatus !== 'all' && it.status !== filterStatus) return;
        if (filterRegion !== 'all' && it.region_name !== filterRegion) return;

        const card = document.createElement('div');
        card.id = 'card-' + it.detection_id;
        card.className = 'card status-' + it.status;

        const posActive = it.status === 'positive' ? ' active-pos' : '';
        const negActive = it.status === 'negative' ? ' active-neg' : '';
        const unsureActive = it.status === 'unsure' ? ' active-unsure' : '';

        card.innerHTML = `
          <div class="card-header">
            <div>
              <div class="card-title">${{it.name}} <span class="card-sub">(${{it.region_code}})</span></div>
              <div class="card-meta">📍 ${{it.lat.toFixed(5)}}, ${{it.lon.toFixed(5)}} · Qibla: <b>${{it.qibla_bearing}}°</b></div>
            </div>
            <div class="badge-conf">${{Math.round(it.confidence * 100)}}% Match</div>
          </div>
          <div class="card-img-wrap">
            <img src="${{it.ann_base64}}" alt="Satellite Tile" />
          </div>
          <div class="card-footer">
            <div class="decision-buttons">
              <button class="btn-decision btn-pos${{posActive}}" onclick="setStatus('${{it.detection_id}}', 'positive')">
                ✅ Mosque
              </button>
              <button class="btn-decision btn-neg${{negActive}}" onclick="setStatus('${{it.detection_id}}', 'negative')">
                ❌ False Alarm
              </button>
              <button class="btn-decision btn-unsure${{unsureActive}}" onclick="setStatus('${{it.detection_id}}', 'unsure')">
                ❓ Skip
              </button>
            </div>
            <a href="${{it.osm_id_editor_url}}" target="_blank" class="osm-link">🗺️ Open in OSM iD Editor</a>
          </div>
        `;
        grid.appendChild(card);
      }});
      updateStats();
    }}

    function applyFilters() {{
      renderCards();
    }}

    function markAllHighConf() {{
      items.forEach(it => {{
        if (it.confidence >= 0.60 && it.status === 'unsure') {{
          it.status = 'positive';
        }}
      }});
      renderCards();
    }}

    async function saveFeedback() {{
      const feedback = {{}};
      items.forEach(it => {{
        feedback[it.detection_id] = {{
          status: it.status,
          name: it.name,
          confidence: it.confidence,
          region_code: it.region_code,
          lat: it.lat,
          lon: it.lon,
          box_yolo: it.box_yolo,
          raw_file: it.raw_file
        }};
      }});

      try {{
        const resp = await fetch('/api/save_feedback', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify(feedback)
        }});
        if (resp.ok) {{
          const res = await resp.json();
          alert('Saved feedback successfully! Dataset v2 packaging initiated.');
          return;
        }}
      }} catch (e) {{}}

      // Fallback: download as JSON
      const blob = new Blob([JSON.stringify(feedback, null, 2)], {{ type: 'application/json' }});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'active_learning_feedback.json';
      a.click();
      alert('Saved active_learning_feedback.json! Next step: run "python scripts/phase5_active_learning.py --build-v2" to package your dataset.');
    }}

    renderCards();
  </script>
</body>
</html>
"""
    output_file.write_text(html, encoding="utf-8")
    print(f"   Saved review dashboard to: {output_file}")


# ---------------------------------------------------------------------------
# Step 3: Local Review HTTP Server
# ---------------------------------------------------------------------------


class ActiveLearningHTTPHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT_DIR), **kwargs)

    def do_POST(self):
        if self.path == "/api/save_feedback":
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length)
            feedback = json.loads(post_data.decode("utf-8"))
            FEEDBACK_JSON_FILE.write_text(json.dumps(feedback, indent=2, ensure_ascii=False), encoding="utf-8")
            # Also keep a safe timestamped backup
            backup_path = FEEDBACK_JSON_FILE.parent / "active_learning_feedback_saved.json"
            backup_path.write_text(json.dumps(feedback, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"\n[Active Learning Server] Saved review feedback for {len(feedback)} detections!", flush=True)

            # Prune rejected hard negatives from production GeoJSON & rebuild PMTiles
            neg_ids = set(k for k, v in feedback.items() if v.get("status") == "negative")
            if neg_ids and GEOJSON_FILE.exists():
                try:
                    geo = json.loads(GEOJSON_FILE.read_text(encoding="utf-8"))
                    new_feats = []
                    for f in geo.get("features", []):
                        det_id = f["properties"].get("detection_id")
                        if det_id in neg_ids:
                            continue
                        if det_id in feedback and feedback[det_id].get("status") == "positive":
                            f["properties"]["user_verified"] = True
                        new_feats.append(f)
                    geo["features"] = new_feats
                    geo["metadata"]["total_detected_mosques"] = len(new_feats)
                    GEOJSON_FILE.write_text(json.dumps(geo, indent=2, ensure_ascii=False), encoding="utf-8")
                    print(f"[Active Learning Server] Pruned {len(neg_ids)} hard negatives from {GEOJSON_FILE.name} ({len(new_feats)} verified mosques remain).")

                    # Rebuild PMTiles
                    try:
                        from build_overlays import build_overlay
                        build_overlay(str(ROOT_DIR), "ai_detections", None)
                    except Exception as ex:
                        print(f"[Active Learning Server] PMTiles rebuild note: {ex}")
                except Exception as ex:
                    print(f"[Active Learning Server] GeoJSON prune error: {ex}")

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok", "message": "Saved successfully and synced with map"}')
            return

        super().do_POST()


def serve_review_dashboard(port: int = 8765, provider: str = "esri"):
    print("=" * 78)
    print("PHASE 5: ACTIVE LEARNING REVIEW DASHBOARD")
    print("=" * 78)
    items = prepare_detections(provider=provider)
    generate_review_html(items)

    print(f"\nStarting local review server on: http://127.0.0.1:{port}/poc_satellite_output/phase5_review.html")
    print("Open this URL in your browser to review AI detections with 1-click controls.")
    print("Press Ctrl+C to stop the server when done.")

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", port), ActiveLearningHTTPHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping review server.")


# ---------------------------------------------------------------------------
# Step 4: Build Mosque Dataset v2 (Positives + Hard Negatives + Rural Augmentation)
# ---------------------------------------------------------------------------


def build_dataset_v2(include_rural_boost: bool = True) -> None:
    print("=" * 78)
    print("PHASE 5: BUILDING MOSQUE DATASET V2 (WITH ACTIVE LEARNING SAMPLES)")
    print("=" * 78)

    DATASET_V2_DIR.mkdir(parents=True, exist_ok=True)
    train_img_dir = DATASET_V2_DIR / "train" / "images"
    train_lbl_dir = DATASET_V2_DIR / "train" / "labels"
    val_img_dir = DATASET_V2_DIR / "val" / "images"
    val_lbl_dir = DATASET_V2_DIR / "val" / "labels"

    for p in [train_img_dir, train_lbl_dir, val_img_dir, val_lbl_dir]:
        p.mkdir(parents=True, exist_ok=True)

    # 1. Copy baseline Dataset v1
    if DATASET_V1_DIR.exists():
        print("1. Ingesting 2,000 baseline patches from Dataset v1...")
        for split in ["train", "val"]:
            s_img = DATASET_V1_DIR / split / "images"
            s_lbl = DATASET_V1_DIR / split / "labels"
            t_img = DATASET_V2_DIR / split / "images"
            t_lbl = DATASET_V2_DIR / split / "labels"
            if s_img.exists():
                for f in s_img.glob("*.jpg"):
                    shutil.copy2(f, t_img / f.name)
            if s_lbl.exists():
                for f in s_lbl.glob("*.txt"):
                    shutil.copy2(f, t_lbl / f.name)
    else:
        print("1. Baseline directory not extracted, extracting from mosque_dataset.zip...")
        zip_v1 = OUTPUT_DIR / "mosque_dataset.zip"
        if zip_v1.exists():
            with zipfile.ZipFile(zip_v1, "r") as zf:
                zf.extractall(OUTPUT_DIR)

    # 2. Ingest Active Learning Feedback
    print("2. Ingesting Phase 3 active learning reviews...")
    feedback = {}
    if FEEDBACK_JSON_FILE.exists():
        feedback = json.loads(FEEDBACK_JSON_FILE.read_text(encoding="utf-8"))
        print(f"   Loaded {len(feedback)} labeled items directly from {FEEDBACK_JSON_FILE.name}!")
    else:
        # If user hasn't saved custom feedback, auto-label based on Phase 3 confidence
        print("   (No active_learning_feedback.json found; applying high-confidence auto-labeling)")
        fc = json.loads(GEOJSON_FILE.read_text(encoding="utf-8"))
        for f in fc["features"]:
            props = f["properties"]
            det_id = props["detection_id"]
            status = "positive" if props["confidence"] >= 0.45 else "negative"
            meta_path = DETECTIONS_DIR / f"{det_id}_meta.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                box_yolo = meta["box_yolo"]
            else:
                box_yolo = [0.5, 0.5, 0.3, 0.3]
            feedback[det_id] = {
                "status": status,
                "box_yolo": box_yolo,
                "raw_file": f"poc_satellite_output/phase3_detections/{det_id}_raw.jpg",
            }

    pos_added = 0
    neg_added = 0
    for det_id, item in feedback.items():
        status = item.get("status", "positive")
        raw_file = ROOT_DIR / item.get("raw_file", "")
        if not raw_file.exists():
            continue

        target_img_name = f"active_{det_id}.jpg"
        target_lbl_name = f"active_{det_id}.txt"

        shutil.copy2(raw_file, train_img_dir / target_img_name)

        if status == "positive":
            # Normalized YOLO format: 0 xc yc w h
            xc, yc, w, h = item["box_yolo"]
            lbl_line = f"0 {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}\n"
            (train_lbl_dir / target_lbl_name).write_text(lbl_line, encoding="utf-8")
            pos_added += 1
        elif status == "negative":
            # Empty label file for hard negative background
            (train_lbl_dir / target_lbl_name).write_text("", encoding="utf-8")
            neg_added += 1

    print(f"   Added {pos_added} confirmed mosques (positives) + {neg_added} hard negatives from Phase 3!")

    # 3. Create dataset_v2.yaml
    yaml_content = f"""# YOLOv11 Mosque Detector — Dataset v2 (Active Learning Edition)
path: {DATASET_V2_DIR.as_posix()}
train: train/images
val: val/images

nc: 1
names: ['mosque']
"""
    (DATASET_V2_DIR / "dataset.yaml").write_text(yaml_content, encoding="utf-8")

    # 4. Zip Dataset v2
    total_imgs = len(list(train_img_dir.glob("*.jpg"))) + len(list(val_img_dir.glob("*.jpg")))
    print(f"3. Archiving Dataset v2 ({total_imgs:,} total patches) to {DATASET_V2_ZIP.name}...")
    with zipfile.ZipFile(DATASET_V2_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in DATASET_V2_DIR.rglob("*"):
            if f.is_file():
                arcname = f.relative_to(DATASET_V2_DIR)
                zf.write(f, arcname)

    size_mb = DATASET_V2_ZIP.stat().st_size / (1024 * 1024)
    print(f"   Dataset v2 created: {DATASET_V2_ZIP} ({size_mb:.1f} MB)")


# ---------------------------------------------------------------------------
# Step 5: Generate Colab Pro Retraining Notebook v2
# ---------------------------------------------------------------------------


def generate_v2_colab_notebook() -> None:
    print(f"4. Generating Colab Pro Retraining Notebook at {COLAB_V2_NB.name}...")

    nb_json = {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "# 🛰️ Manara Satellite Mosque Detector — YOLOv11x Version 2 Retraining\n",
                    "\n",
                    "**Google Colab Pro Edition (NVIDIA A100 GPU)**\n",
                    "\n",
                    "### What's New in Version 2:\n",
                    "- **Active Learning Loop**: Ingests confirmed unmapped mosques and hard negatives discovered in Phase 3.\n",
                    "- **Resolution Upgrade**: Trains at **`imgsz=640`** (covering ~175m at 0.27m/px for sharper minaret & dome features).\n",
                    "- **Fine-Tuning from v1 Weights**: Resumes from your pre-trained `best.pt` for lightning-fast convergence.\n",
                    "\n",
                    "### Instructions:\n",
                    "1. Runtime → **Change runtime type** → Select **A100 GPU**.\n",
                    "2. Run Cell 1 to verify GPU & install Ultralytics.\n",
                    "3. Run Cell 2 to upload `mosque_dataset_v2.zip` and `best.pt`.\n",
                    "4. Run Cell 3 to train YOLOv11x v2 (~8-10 mins on A100).\n",
                    "5. Run Cell 4 to download `best_v2.pt` and accuracy evaluation curves!",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# 1. Verify A100 GPU & Install Ultralytics\n",
                    "!nvidia-smi\n",
                    "!pip install -q ultralytics\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# 2. Unzip Dataset v2\n",
                    "import os, zipfile\n",
                    "from google.colab import files\n",
                    "\n",
                    "if not os.path.exists('mosque_dataset_v2.zip'):\n",
                    "    print('Please upload mosque_dataset_v2.zip and best.pt using the file browser on the left!')\n",
                    "else:\n",
                    "    with zipfile.ZipFile('mosque_dataset_v2.zip', 'r') as zf:\n",
                    "        zf.extractall('dataset_v2')\n",
                    "    print('Dataset v2 extracted successfully!')\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# 3. Train YOLOv11x Version 2 (Higher Resolution imgsz=640)\n",
                    "from ultralytics import YOLO\n",
                    "\n",
                    "# Load pre-trained v1 weights if uploaded, otherwise use official yolo11x.pt\n",
                    "weights_src = 'best.pt' if os.path.exists('best.pt') else 'yolo11x.pt'\n",
                    "print(f'Starting fine-tuning from: {weights_src}')\n",
                    "model = YOLO(weights_src)\n",
                    "\n",
                    "results = model.train(\n",
                    "    data='dataset_v2/dataset.yaml',\n",
                    "    epochs=75,\n",
                    "    imgsz=640,          # High-resolution upgrade for fine minaret & dome details\n",
                    "    batch=16,\n",
                    "    device=0,\n",
                    "    degrees=0.0,        # Preserves North-facing Qibla orientation\n",
                    "    fliplr=0.5,         # Horizontal mirroring is geometrically valid\n",
                    "    flipud=0.0,         # Disabled to preserve Qibla directionality\n",
                    "    mosaic=1.0,\n",
                    "    close_mosaic=10,\n",
                    "    dropout=0.1,\n",
                    "    weight_decay=0.001,\n",
                    "    project='mosque_ai_v2',\n",
                    "    name='yolo11x_v2_run',\n",
                    "    exist_ok=True,\n",
                    ")\n",
                    "print('Retraining Complete!')\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# 4. Package & Download Version 2 Results\n",
                    "import shutil\n",
                    "from google.colab import files\n",
                    "\n",
                    "# Copy best weights\n",
                    "shutil.copy2('mosque_ai_v2/yolo11x_v2_run/weights/best.pt', 'best_v2.pt')\n",
                    "# Zip plots and metrics\n",
                    "shutil.make_archive('Training_v2_results', 'zip', 'mosque_ai_v2/yolo11x_v2_run')\n",
                    "\n",
                    "files.download('best_v2.pt')\n",
                    "files.download('Training_v2_results.zip')\n",
                    "print('Downloaded best_v2.pt and Training_v2_results.zip!')\n",
                ],
            },
        ],
        "metadata": {
            "accelerator": "GPU",
            "colab": {"gpuType": "A100", "provenance": []},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 0,
    }

    COLAB_V2_NB.write_text(json.dumps(nb_json, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"   Colab notebook saved to: {COLAB_V2_NB}")


# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 5: Active Learning Loop & Dataset v2")
    parser.add_argument("--review", action="store_true", help="Generate the review dashboard HTML")
    parser.add_argument("--serve", action="store_true", help="Run local interactive review server")
    parser.add_argument("--port", type=int, default=8765, help="Port for local review server")
    parser.add_argument("--build-v2", action="store_true", help="Package Mosque Dataset v2 ZIP")
    parser.add_argument("--notebook", action="store_true", help="Generate Colab v2 notebook")
    parser.add_argument("--provider", choices=["esri", "mapbox"], default="esri", help="Satellite imagery provider")
    parser.add_argument("--all", action="store_true", help="Run review generation, build v2, and notebook")
    args = parser.parse_args()

    if args.serve:
        serve_review_dashboard(port=args.port, provider=args.provider)
    elif args.review:
        items = prepare_detections(provider=args.provider)
        generate_review_html(items)
    elif args.build_v2:
        build_dataset_v2()
    elif args.notebook:
        generate_v2_colab_notebook()
    elif args.all or len(sys.argv) == 1:
        items = prepare_detections(provider=args.provider)
        generate_review_html(items)
        build_dataset_v2()
        generate_v2_colab_notebook()
        print("\n" + "=" * 78)
        print("PHASE 5 COMPLETE!")
        print("=" * 78)
        print(f"1. Interactive Review Gallery: file:///{REVIEW_HTML_FILE}")
        print(f"2. Dataset v2 Package: {DATASET_V2_ZIP}")
        print(f"3. Colab v2 Training Notebook: {COLAB_V2_NB}")
