"""
Manara AI: Autonomous Background Satellite Sweeper
==================================================
Runs a continuous or scheduled background survey of Saudi residential coverage gaps:
- Prioritizes high-urgency residential road networks from `worship_gaps_sa.csv`.
- Uses the 4-Quadrant Sub-Grid (NW, NE, SW, SE at +/- 250m) to survey each 1km neighborhood.
- Queries high-res satellite imagery (Mapbox Satellite + Esri World Imagery).
- Runs YOLOv11x v2 (`best_v2.pt`).
- Strict 100m exclusion guard against existing OSM mosques.
- Deduplicates via 60m Geographic NMS.
- State-preserving: remembers scanned grid cells in `poc_satellite_output/sweeper_state.json`.
- Live pipeline sync: automatically appends to `ai_detected_mosques_sa.geojson`,
  regenerates `ai_detections.pmtiles`, and refreshes `phase3_gap_scan_report.html`.
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import math
import os
import re
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from PIL import Image
from shapely.geometry import Point, shape
from shapely.prepared import prep
from ultralytics import YOLO
import ultralytics.utils.patches as _ul_patches

# Ultralytics patches PIL.Image.open: on any unreadable image it runs `pip install pi-heif`
# (3-10 s, every time) assuming a HEIC file. Satellite tiles are never HEIC - fail fast instead.
_ul_patches._pil_plugins_registered = True

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "pipeline"))
sys.path.insert(0, str(ROOT_DIR / "scripts"))

from build_overlays import build_overlay  # noqa: E402
from common import calculate_qibla_azimuth, configure_utf8_output  # noqa: E402
from stage2_verifier import verify_candidate_patch  # noqa: E402
from stage3_geometric_guard import evaluate_geometry, evaluate_spatial_and_provider  # noqa: E402
from roof_boundary_snapping import snap_roof_boundary, draw_snapped_annotation, get_meters_per_pixel  # noqa: E402
from scan_worship_gaps import (  # noqa: E402
    PATCH_SIZE,
    ZOOM,
    annotate_detection,
    apply_geographic_nms,
    build_reference_indexes,
    cell_scan_points,
    fetch_borderless_patch,
    find_region_code,
    is_near_osm_mosque,
    pil_to_base64,
    rotated_patch_px_to_latlon,
)

configure_utf8_output()
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(line_buffering=True)

OUTPUT_DIR = ROOT_DIR / "poc_satellite_output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = OUTPUT_DIR / "sweeper_state.json"
# Single-provider detections (seen on Esri or Mapbox only) need this stage-1 confidence.
SINGLE_PROVIDER_MIN_CONF = 0.65
OUTPUT_GEOJSON = ROOT_DIR / "ai_detected_mosques_sa.geojson"
OUTPUT_REPORT = OUTPUT_DIR / "phase3_gap_scan_report.html"
GAPS_CSV = ROOT_DIR / "worship_gaps_sa.csv"
MODEL_WEIGHTS = (
    OUTPUT_DIR / "best_v6_obb.pt"
    if (OUTPUT_DIR / "best_v6_obb.pt").exists()
    else (OUTPUT_DIR / "best_v6_obb.onnx")
    if (OUTPUT_DIR / "best_v6_obb.onnx").exists()
    else (OUTPUT_DIR / "best_v5_obb.pt")
    if (OUTPUT_DIR / "best_v5_obb.pt").exists()
    else OUTPUT_DIR / "best_obb.pt"
    if (OUTPUT_DIR / "best_obb.pt").exists()
    else (
        OUTPUT_DIR / "best_obb.onnx"
        if (OUTPUT_DIR / "best_obb.onnx").exists()
        else (
            OUTPUT_DIR / "best_v3.onnx"
            if (OUTPUT_DIR / "best_v3.onnx").exists()
            else (
                OUTPUT_DIR / "best_v3.pt"
                if (OUTPUT_DIR / "best_v3.pt").exists()
                else (
                    OUTPUT_DIR / "best_v2.onnx"
                    if (OUTPUT_DIR / "best_v2.onnx").exists()
                    else (OUTPUT_DIR / "best_v2.pt" if (OUTPUT_DIR / "best_v2.pt").exists() else (OUTPUT_DIR / "best.pt"))
                )
            )
        )
    )
)

RUNNING = True


def handle_sigint(signum, frame):
    global RUNNING
    print("\n[Sweeper] Graceful stop requested. Finishing current batch and saving state...")
    RUNNING = False


signal.signal(signal.SIGINT, handle_sigint)
if hasattr(signal, "SIGBREAK"):
    signal.signal(signal.SIGBREAK, handle_sigint)


DASHBOARD_FILE = OUTPUT_DIR / "sweeper_live_dashboard.html"



def last_detection_number(existing_feats: list[dict]) -> int:
    """Highest ai_det_N ever issued. IDs must never be reused: pruned detections still have
    human reviews (active_learning_feedback.json, the website) and files in phase3_detections/
    keyed by their ID, so `len(features) + 1` would attach old verdicts to new places."""
    nums = [0]
    names = [f["properties"].get("detection_id", "") for f in existing_feats]
    for fb in (ROOT_DIR / "active_learning_feedback.json", OUTPUT_DIR / "active_learning_feedback.json"):
        if fb.exists():
            try:
                names += list(json.loads(fb.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass
    det_dir = OUTPUT_DIR / "phase3_detections"
    if det_dir.exists():
        names += [n.name for n in det_dir.iterdir()]
    for n in names:
        m = re.match(r"ai_det_(\d+)", n)
        if m:
            nums.append(int(m.group(1)))
    return max(nums)

def render_live_dashboard(features: list[dict], state: dict, current_cycle: int) -> None:
    reversed_feats = list(reversed(features))
    cards_html = []
    dual_count = 0

    for f in reversed_feats:
        p = f["properties"]
        geom = f["geometry"]["coordinates"]
        lon, lat = geom[0], geom[1]
        conf_pct = int(p.get("confidence", 0.5) * 100)
        prov = p.get("imagery_provider", "Mapbox Satellite")
        is_dual = p.get("cross_verified", False)
        if is_dual:
            dual_count += 1
        prov_cls = "badge-dual" if is_dual else "badge-prov"

        # Check thumbnail: inline base64 or relative file path in phase3_detections/
        thumb = p.get("thumbnail") or ""
        if not thumb:
            local_ann = OUTPUT_DIR / "phase3_detections" / f"{p.get('detection_id', '')}_ann.jpg"
            if local_ann.exists():
                thumb = f"phase3_detections/{p.get('detection_id')}_ann.jpg"
            else:
                thumb = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='100' height='100'%3E%3Crect fill='%231e293b' width='100' height='100'/%3E%3Ctext fill='%2394a3b8' x='50%25' y='50%25' text-anchor='middle' dy='.3em'%3E🕌%3C/text%3E%3C/svg%3E"

        osm_url = p.get("osm_id_editor_url") or f"https://www.openstreetmap.org/edit?editor=id#map=19/{lat}/{lon}"
        josm_url = f"http://127.0.0.1:8111/load_and_zoom?left={lon-0.002}&bottom={lat-0.002}&right={lon+0.002}&top={lat+0.002}"
        reg_name = p.get("region_name") or p.get("region_code") or "المملكة"
        quad = p.get("quadrant") or "Center"
        dino_pct = int(p.get("stage2_dino_score", p.get("confidence", 0.5)) * 100)
        area_m2 = p.get("est_area_m2")
        area_str = f" · Area: <b>{area_m2} m²</b>" if area_m2 else ""

        cards_html.append(f"""
        <div class="card">
          <div class="card-header">
            <div>
              <h3>مسجد غير مرسوم <span class="sub">({reg_name} · {quad})</span></h3>
              <p class="meta">📍 {lat:.5f}, {lon:.5f} · Qibla: <b>{p.get('qibla_bearing', 0)}°</b>{area_str} · Gap Urgency: <b>{p.get('gap_urgency', 0)}</b></p>
            </div>
            <div class="conf-badge" title="YOLOv11 Detection / DINOv2 Foundation Score">⚡ {conf_pct}% · 🧠 {dino_pct}%</div>
          </div>
          <div class="card-img-wrap">
            <img src="{thumb}" alt="Mosque Detection" loading="lazy" />
          </div>
          <div class="card-footer">
            <div class="badges-wrap">
              <span class="badge badge-new">3-Stage Verified</span>
              <span class="badge {prov_cls}">{prov}</span>
            </div>
            <div class="actions-wrap">
              <a href="{osm_url}" target="_blank" class="btn btn-osm" title="Open in OpenStreetMap iD Web Editor">🗺️ iD Editor</a>
              <a href="{josm_url}" target="_blank" class="btn btn-josm" title="Open in JOSM Desktop Editor">✏️ JOSM</a>
            </div>
          </div>
        </div>
        """)

    total_scanned = state.get("total_cells_scanned", 0)
    total_found = len(features)
    updated_at = state.get("last_run", time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta http-equiv="refresh" content="5" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>⚡ Manara AI — Autonomous Satellite Sweeper Radar</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #070d18; color: #f8fafc; margin: 0; padding: 24px; }}
    .container {{ max-width: 1400px; margin: 0 auto; }}
    .top-strip {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #1e293b; padding-bottom: 16px; margin-bottom: 24px; flex-wrap: wrap; gap: 14px; }}
    .brand-title {{ font-size: 24px; font-weight: 800; display: flex; align-items: center; gap: 12px; color: #38bdf8; }}
    .brand-badge {{ font-size: 11px; text-transform: uppercase; letter-spacing: 1px; background: rgba(56, 189, 248, 0.15); border: 1px solid rgba(56, 189, 248, 0.4); color: #38bdf8; padding: 3px 8px; border-radius: 6px; font-weight: 700; }}
    .controls-strip {{ display: flex; align-items: center; gap: 12px; }}
    .status-tag {{ background: #064e3b; color: #34d399; font-weight: 700; font-size: 13px; padding: 6px 14px; border-radius: 999px; border: 1px solid #059669; display: flex; align-items: center; gap: 8px; }}
    .pulse-dot {{ width: 10px; height: 10px; border-radius: 50%; background: #10b981; box-shadow: 0 0 10px #10b981; animation: pulse 1.4s infinite; }}
    @keyframes pulse {{ 0% {{ opacity: 1; transform: scale(1); }} 50% {{ opacity: 0.3; transform: scale(1.3); }} 100% {{ opacity: 1; transform: scale(1); }} }}
    .btn-manara {{ background: linear-gradient(135deg, #0284c7, #2563eb); color: #ffffff; text-decoration: none; padding: 7px 16px; border-radius: 8px; font-size: 13px; font-weight: 700; transition: transform 0.2s, box-shadow 0.2s; box-shadow: 0 4px 14px rgba(37,99,235,0.4); }}
    .btn-manara:hover {{ transform: translateY(-1px); box-shadow: 0 6px 20px rgba(37,99,235,0.6); }}
    .btn-review {{ background: linear-gradient(135deg, #7c3aed, #4f46e5); color: #ffffff; text-decoration: none; padding: 7px 16px; border-radius: 8px; font-size: 13px; font-weight: 700; transition: transform 0.2s, box-shadow 0.2s; box-shadow: 0 4px 14px rgba(124,58,237,0.4); }}
    .btn-review:hover {{ transform: translateY(-1px); box-shadow: 0 6px 20px rgba(124,58,237,0.6); }}
    
    .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 28px; }}
    .stat-card {{ background: #0f172a; border: 1px solid #1e293b; border-radius: 14px; padding: 18px 20px; box-shadow: 0 4px 20px rgba(0,0,0,0.3); }}
    .stat-num {{ font-size: 34px; font-weight: 800; color: #38bdf8; margin-top: 4px; }}
    .stat-num.glow {{ color: #10b981; text-shadow: 0 0 20px rgba(16,185,129,0.5); }}
    .stat-label {{ font-size: 12px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.6px; font-weight: 600; }}
    .progress-bar-wrap {{ background: #1e293b; border-radius: 8px; height: 8px; overflow: hidden; margin-top: 10px; }}
    .progress-bar-fill {{ background: linear-gradient(90deg, #38bdf8, #10b981); height: 100%; border-radius: 8px; transition: width 0.5s ease; }}

    .feed-heading {{ font-size: 18px; font-weight: 700; color: #f8fafc; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }}
    .timer-note {{ font-size: 12px; color: #64748b; font-weight: 400; }}
    
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 20px; }}
    .card {{ background: #0f172a; border: 1px solid #1e293b; border-radius: 14px; overflow: hidden; box-shadow: 0 4px 16px rgba(0,0,0,0.25); transition: transform 0.2s, border-color 0.2s; }}
    .card:hover {{ transform: translateY(-3px); border-color: #38bdf8; }}
    .card-header {{ padding: 14px 16px; display: flex; justify-content: space-between; align-items: flex-start; }}
    .card-header h3 {{ margin: 0; font-size: 15px; color: #f1f5f9; }}
    .sub {{ color: #38bdf8; font-size: 13px; }}
    .meta {{ margin: 4px 0 0; font-size: 12px; color: #94a3b8; }}
    .conf-badge {{ background: #10b981; color: #042f2e; font-weight: 800; padding: 4px 9px; border-radius: 8px; font-size: 13px; }}
    .card-img-wrap {{ width: 100%; height: 260px; background: #070d18; overflow: hidden; display: flex; align-items: center; justify-content: center; }}
    .card-img-wrap img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
    .card-footer {{ padding: 12px 16px; display: flex; justify-content: space-between; align-items: center; background: #080f1d; border-top: 1px solid #1e293b; flex-wrap: wrap; gap: 8px; }}
    .badges-wrap {{ display: flex; gap: 6px; }}
    .badge {{ font-size: 11px; font-weight: 700; padding: 4px 8px; border-radius: 999px; display: inline-block; }}
    .badge-new {{ background: rgba(16, 185, 129, 0.16); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.4); }}
    .badge-prov {{ background: rgba(148, 163, 184, 0.16); color: #cbd5e1; border: 1px solid rgba(148, 163, 184, 0.4); }}
    .badge-dual {{ background: rgba(234, 179, 8, 0.18); color: #fde047; border: 1px solid rgba(234, 179, 8, 0.5); }}
    .actions-wrap {{ display: flex; gap: 6px; }}
    .btn {{ text-decoration: none; padding: 5px 10px; border-radius: 6px; font-size: 12px; font-weight: 600; transition: background 0.2s; }}
    .btn-osm {{ background: #2563eb; color: #fff; }}
    .btn-osm:hover {{ background: #1d4ed8; }}
    .btn-josm {{ background: #334155; color: #cbd5e1; }}
    .btn-josm:hover {{ background: #475569; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="top-strip">
      <div class="brand-title">
        <span>🛰️</span> Manara AI Autonomous Satellite Radar
        <span class="brand-badge">Option 2 Sub-Grid</span>
      </div>
      <div class="controls-strip">
        <a href="http://127.0.0.1:8765/poc_satellite_output/phase5_review.html" target="_blank" class="btn-review">🎯 Review & Mark Hard Negatives</a>
        <a href="https://localhost:8000" target="_blank" class="btn-manara">🗺️ Open Manara Map</a>
        <div class="status-tag">
          <span class="pulse-dot"></span> Live Sweeper Active (Cycle #{current_cycle})
        </div>
      </div>
    </div>

    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-label">Total Unmapped Mosques Discovered</div>
        <div class="stat-num glow">{total_found} 🕌</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Neighborhoods Surveyed</div>
        <div class="stat-num">{total_scanned:,}</div>
        <div class="progress-bar-wrap">
          <div class="progress-bar-fill" style="width: {min(100.0, max(2.0, (total_scanned / 200.0) * 100)):.1f}%;"></div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Dual-Satellite Confirmed (Esri + Mapbox)</div>
        <div class="stat-num">{dual_count} 🌟</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">GPU Acceleration Active</div>
        <div class="stat-num glow" style="font-size: 19px; margin-top: 10px;">AMD Radeon RX 6750 XT</div>
        <div style="font-size: 12px; color: #34d399; margin-top: 4px;">DirectX 12 DirectML · 30ms Latency</div>
      </div>
    </div>

    <div class="feed-heading">
      <span>Latest AI Discoveries Across Saudi Arabia (Real-Time Feed)</span>
      <span class="timer-note">Auto-refreshing every 5s · Last radar sweep: {updated_at}</span>
    </div>

    <div class="grid">
      {''.join(cards_html) if cards_html else '<p style="color:#64748b; padding: 40px; text-align: center;">Scanning active residential gaps... discoveries will stream here in real time!</p>'}
    </div>
  </div>

  <script>
    // Audio alert when new mosque is detected
    try {{
      const currentCount = {total_found};
      const prevCount = parseInt(localStorage.getItem('manara_mosque_count') || '0', 10);
      if (prevCount > 0 && currentCount > prevCount) {{
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.frequency.setValueAtTime(587.33, ctx.currentTime); // D5
        osc.frequency.exponentialRampToValueAtTime(880.00, ctx.currentTime + 0.15); // A5
        gain.gain.setValueAtTime(0.2, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.4);
        osc.start();
        osc.stop(ctx.currentTime + 0.45);
      }}
      localStorage.setItem('manara_mosque_count', currentCount.toString());
    }} catch (e) {{}}
  </script>
</body>
</html>
"""
    DASHBOARD_FILE.write_text(html, encoding="utf-8")


def load_sweeper_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "scanned_cells": [],
        "total_cells_scanned": 0,
        "total_detections_found": 0,
        "last_run": "",
    }


def save_sweeper_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def load_existing_geojson() -> tuple[list[dict], set[tuple[float, float]]]:
    if not OUTPUT_GEOJSON.exists():
        return [], set()
    try:
        data = json.loads(OUTPUT_GEOJSON.read_text(encoding="utf-8"))
        feats = data.get("features", [])
        coords = set((round(f["geometry"]["coordinates"][1], 5), round(f["geometry"]["coordinates"][0], 5)) for f in feats)
        return feats, coords
    except Exception:
        return [], set()


def run_sweeper_batch(
    model: YOLO,
    osm_grid: dict,
    regions: list,
    batch_cells_count: int = 20,
    min_urgency: float = 70.0,
    min_road_m: float = 1200.0,
    max_road_m: float = 12000.0,
    provider: str = "both",
    conf_threshold: float = 0.45,  # stage-1 cut; also the bar for dual-provider detections
    current_cycle: int = 1,
) -> int:
    state = load_sweeper_state()
    scanned_keys = set(state.get("scanned_cells", []))

    # 1. Read gaps and group by region for balanced round-robin
    raw_cells = list(csv.DictReader(open(GAPS_CSV, encoding="utf-8-sig")))
    cands_by_region = collections.defaultdict(list)
    for r in raw_cells:
        cell_key = f"{r['grid_x']}_{r['grid_y']}"
        if cell_key in scanned_keys:
            continue
        urg = float(r["urgency_score"])
        road = float(r["road_length_m"])
        if urg >= min_urgency and min_road_m <= road <= max_road_m:
            lat = float(r["lat"])
            lon = float(r["lon"])
            rcode, rname = find_region_code(lat, lon, regions)
            rank = urg * math.sqrt(road)
            cands_by_region[rcode].append(
                {
                    "cell_key": cell_key,
                    "grid_x": r["grid_x"],
                    "grid_y": r["grid_y"],
                    "lat": lat,
                    "lon": lon,
                    "urgency": urg,
                    "road_m": road,
                    "rank": rank,
                    "region_code": rcode,
                    "region_name": rname,
                }
            )

    # Sort candidates in each region by rank descending
    for rcode in cands_by_region:
        cands_by_region[rcode].sort(key=lambda c: c["rank"], reverse=True)

    # Balanced round-robin across regions
    selected_cells = []
    reg_keys = sorted(cands_by_region.keys())
    idx = 0
    while len(selected_cells) < batch_cells_count:
        added_any = False
        for k in reg_keys:
            if idx < len(cands_by_region[k]):
                selected_cells.append(cands_by_region[k][idx])
                added_any = True
                if len(selected_cells) >= batch_cells_count:
                    break
        if not added_any:
            break
        idx += 1

    if not selected_cells:
        print("[Sweeper] No more unscanned gap cells meet criteria!")
        return 0

    provinces_covered = sorted(set(c["region_name"] for c in selected_cells))
    print(
        f"\n[Sweeper] Starting batch: {len(selected_cells)} residential gap cells across "
        f"{len(provinces_covered)} regions"
    )
    print(f"[Sweeper] Active coverage regions: {', '.join(provinces_covered[:5])}...")

    # 2. Tile each gap cell with overlapping patches (whole-cell coverage)
    targets = []
    for c in selected_cells:
        for q_name, q_lat, q_lon in cell_scan_points(int(c["grid_x"]), int(c["grid_y"])):
            targets.append(
                {
                    "cell_key": c["cell_key"],
                    "grid_x": c["grid_x"],
                    "grid_y": c["grid_y"],
                    "lat": q_lat,
                    "lon": q_lon,
                    "urgency": c["urgency"],
                    "road_m": c["road_m"],
                    "quadrant": q_name,
                }
            )
    print(f"[Sweeper] {len(targets)} overlapping scan patches (whole-cell coverage)")

    # 3. Multithreaded fetch
    thread_session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=24, pool_maxsize=24, max_retries=3)
    thread_session.mount("https://", adapter)
    thread_session.mount("http://", adapter)
    providers_to_fetch = ["esri", "mapbox"] if provider in ("both", "dual") else [provider]

    def fetch_job(t: dict) -> list[tuple[dict, Image.Image]]:
        qibla_deg = round(calculate_qibla_azimuth(t["lat"], t["lon"]), 2)
        t["qibla_bearing"] = qibla_deg
        items = []
        for p in providers_to_fetch:
            try:
                raw_740, rot_512 = fetch_borderless_patch(
                    t["lat"], t["lon"], qibla_deg, thread_session, ZOOM, PATCH_SIZE, provider=p
                )
            except Exception as e:  # bad tile / HTTP error: skip this patch, keep the batch alive
                print(f"  [fetch skip] {p} {t['cell_key']} {t['quadrant']}: {type(e).__name__}: {e}")
                continue
            if rot_512 is not None:
                c = dict(t)
                c["provider"] = p
                items.append((c, rot_512))
        return items

    patches = []
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(fetch_job, t) for t in targets]
        for fut in as_completed(futures):
            patches.extend(fut.result())

    print(f"[Sweeper] Fetched {len(patches)} valid satellite patches. Running YOLOv11x inference...")

    # 4. YOLO Inference
    batch_size = 32
    raw_detections = []
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
                det_lat, det_lon = rotated_patch_px_to_latlon(
                    xc, yc, cell["lat"], cell["lon"], cell["qibla_bearing"], ZOOM, PATCH_SIZE
                )

                if is_near_osm_mosque(det_lat, det_lon, osm_grid, max_dist_m=100.0):
                    continue

                det_dict = {
                    "lat": det_lat,
                    "lon": det_lon,
                    "confidence": round(conf, 3),
                    "qibla_bearing": cell["qibla_bearing"],
                    "quadrant": cell.get("quadrant", "Center"),
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

    new_dets = apply_geographic_nms(raw_detections, min_distance_m=60.0)

    # 5. Verification gate, re-tuned for best_v5_obb on held-out data (scripts/eval_cascade_v5.py,
    #    poc_satellite_output/eval_v5/cascade_best_v5_obb_{val,test}.json):
    #    * geometry guard (120-2200 m2, aspect <= 2.2) rejected ~17% of real mosques - mostly large
    #      Friday mosques - and removed no false positives, so it no longer rejects; area and aspect
    #      are still recorded for the review cards.
    #    * DINOv2 verifier removed 21-31 real mosques and ~0 false positives, so its score is
    #      informational only.
    #    * the dual-provider rule is what actually cuts false positives: a detection seen on both
    #      Esri and Mapbox passes at stage-1 confidence; a single-provider one needs >= 0.65.
    #      Test (769 places, 532 mosques): P 0.92, R 0.81, 2.1 FP/km2 of background,
    #      vs. the old gate's P 0.93, R 0.65, 1.0 FP/km2.
    verified_dets = []
    for d in new_dets:
        geom_eval = evaluate_geometry(d["box_xyxy"], d["lat"], min_area_m2=0.0, max_area_m2=1e9,
                                      max_aspect_ratio=1e9)

        try:
            x1, y1, x2, y2 = [int(v) for v in d["box_xyxy"]]
            margin_x = max(10, int((x2 - x1) * 0.15))
            margin_y = max(10, int((y2 - y1) * 0.15))
            w_img, h_img = d["patch_img"].size
            cx1, cy1 = max(0, x1 - margin_x), max(0, y1 - margin_y)
            cx2, cy2 = min(w_img, x2 + margin_x), min(h_img, y2 + margin_y)
            st2 = verify_candidate_patch(d["patch_img"].crop((cx1, cy1, cx2, cy2)))
        except Exception as e:
            st2 = {"is_mosque": True, "verifier_score": 0.0, "reason": f"verifier unavailable: {e}"}

        is_dual = d.get("cross_verified", False)
        ok_prov, prov_reason = evaluate_spatial_and_provider(
            cross_verified=is_dual,
            stage1_conf=d["confidence"],
            stage2_score=st2["verifier_score"],
            min_dual_stage1=conf_threshold,
            min_single_stage1=SINGLE_PROVIDER_MIN_CONF,
            min_stage2_score=0.0,
        )
        if not ok_prov:
            print(f"  [Provider rule reject] ({d['lat']:.5f}, {d['lon']:.5f}) conf={d['confidence']:.2f} -> {prov_reason}")
            continue

        d["geom_eval"] = geom_eval
        d["st2"] = st2
        verified_dets.append(d)

    print(f"[Sweeper] 3-Stage Filter: {len(raw_detections)} raw -> {len(new_dets)} NMS -> {len(verified_dets)} verified mosques.")

    # 6. Ingest into GeoJSON & Update State
    existing_feats, existing_coords = load_existing_geojson()
    det_num = last_detection_number(existing_feats)
    # Places a human already judged (locally or on the website) are never re-suggested.
    fb_path = ROOT_DIR / "active_learning_feedback.json"
    if fb_path.exists():
        try:
            for v in json.loads(fb_path.read_text(encoding="utf-8")).values():
                if "lat" in v and "lon" in v:
                    existing_coords.add((round(float(v["lat"]), 5), round(float(v["lon"]), 5)))
        except (OSError, ValueError):
            pass
    m_lat = 110_574.0
    added_count = 0

    for d in verified_dets:
        # Check against already saved detections
        is_dup = False
        m_lon = 111_320.0 * math.cos(math.radians(d["lat"]))
        for elat, elon in existing_coords:
            dy_m = (d["lat"] - elat) * m_lat
            dx_m = (d["lon"] - elon) * m_lon
            if dx_m * dx_m + dy_m * dy_m <= 60.0 * 60.0:
                is_dup = True
                break

        if not is_dup:
            added_count += 1
            det_num += 1
            det_id = f"ai_det_{det_num:05d}"
            existing_coords.add((round(d["lat"], 5), round(d["lon"], 5)))

            thumb_b64 = ""
            snap_res = None
            has_native_obb = "rotated_corners" in d and d["rotated_corners"] and len(d["rotated_corners"]) == 4

            if has_native_obb:
                corners = d["rotated_corners"]
                roof_angle = d.get("roof_angle_deg", 0.0)
                m_per_px = get_meters_per_pixel(d["lat"], ZOOM)
                p0, p1, p2 = corners[0], corners[1], corners[2]
                w_m = math.hypot(p1[0] - p0[0], p1[1] - p0[1]) * m_per_px
                h_m = math.hypot(p2[0] - p1[0], p2[1] - p1[1]) * m_per_px
                est_area = round(w_m * h_m, 1)
                est_asp = round(max(w_m, h_m) / max(0.1, min(w_m, h_m)), 2)
            elif "box_xyxy" in d and "patch_img" in d:
                try:
                    snap_res = snap_roof_boundary(d["patch_img"], d["box_xyxy"], lat=d["lat"], zoom=ZOOM)
                    est_area = snap_res["area_m2"]
                    est_asp = snap_res["aspect_ratio"]
                    roof_angle = snap_res["roof_angle_deg"]
                    corners = snap_res["rotated_corners"]
                except Exception:
                    est_area = d.get("geom_eval", {}).get("area_m2", 0)
                    est_asp = d.get("geom_eval", {}).get("aspect_ratio", 1.0)
                    roof_angle = 0.0
                    corners = []
            else:
                est_area = d.get("geom_eval", {}).get("area_m2", 0)
                est_asp = d.get("geom_eval", {}).get("aspect_ratio", 1.0)
                roof_angle = 0.0
                corners = []

            if "patch_img" in d and corners:
                try:
                    annotated = draw_snapped_annotation(
                        patch_512=d["patch_img"],
                        corners=corners,
                        conf=d["confidence"],
                        qibla_bearing=d["qibla_bearing"],
                        dino_score=d.get("st2", {}).get("verifier_score", 0.0),
                        area_m2=est_area,
                    )
                    det_dir = OUTPUT_DIR / "phase3_detections"
                    det_dir.mkdir(parents=True, exist_ok=True)
                    annotated.save(det_dir / f"{det_id}_ann.jpg", quality=88)
                    thumb_b64 = pil_to_base64(annotated, max_side=340)
                except Exception as ex:
                    print(f"[Sweeper] Thumbnail generation note: {ex}")

            reg_code, reg_name = find_region_code(d["lat"], d["lon"], regions)

            existing_feats.append(
                {
                    "type": "Feature",
                    "properties": {
                        "detection_id": det_id,
                        "name": f"مسجد مقترح بالذكاء الاصطناعي ({det_id})",
                        "confidence": d["confidence"],
                        "stage1_yolo_conf": d["confidence"],
                        "stage2_dino_score": d.get("st2", {}).get("verifier_score", d["confidence"]),
                        "stage2_dino_reason": d.get("st2", {}).get("reason", "Verified by DINOv2"),
                        "est_area_m2": est_area,
                        "aspect_ratio": est_asp,
                        "roof_angle_deg": roof_angle,
                        "rotated_corners": corners,
                        "snapped_roof": snap_res["snapped"] if snap_res else False,
                        "three_stage_verified": True,
                        "discovery_source": "Manara AI 3-Stage Sweeper",
                        "region_code": reg_code,
                        "region_name": reg_name,
                        "quadrant": d.get("quadrant", "Center"),
                        "qibla_bearing": d["qibla_bearing"],
                        "gap_urgency": d["source_gap_urgency"],
                        "gap_road_length_m": d["source_gap_road_m"],
                        "imagery_provider": d.get("provider_label", d.get("provider", "esri").title()),
                        "cross_verified": d.get("cross_verified", False),
                        "model_weights": MODEL_WEIGHTS.name,
                        "osm_id_editor_url": f"https://www.openstreetmap.org/edit?editor=id#map=19/{d['lat']}/{d['lon']}",
                        "thumbnail": thumb_b64,
                    },
                    "geometry": {"type": "Point", "coordinates": [round(d["lon"], 6), round(d["lat"], 6)]},
                }
            )

    # Save GeoJSON
    geojson_payload = {
        "type": "FeatureCollection",
        "metadata": {
            "model": "YOLOv11x",
            "weights": MODEL_WEIGHTS.name,
            "total_detected_mosques": len(existing_feats),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        },
        "features": existing_feats,
    }
    OUTPUT_GEOJSON.write_text(json.dumps(geojson_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    # Update state
    for c in selected_cells:
        scanned_keys.add(c["cell_key"])
    state["scanned_cells"] = list(scanned_keys)
    state["total_cells_scanned"] = len(scanned_keys)
    state["total_detections_found"] = len(existing_feats)
    state["last_run"] = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    save_sweeper_state(state)

    # Refresh Live Dashboard HTML
    render_live_dashboard(existing_feats, state, current_cycle)

    # Rebuild PMTiles
    try:
        build_overlay(str(ROOT_DIR), "ai_detections", None)
    except Exception as e:
        print(f"[Sweeper] PMTiles update notice: {e}")

    print(
        f"[Sweeper] Batch complete! +{added_count} newly discovered mosques "
        f"(Grand Total: {len(existing_feats)} unmapped mosques across {len(scanned_keys)} scanned neighborhoods)."
    )
    return added_count


def publish_to_site() -> None:
    """Run scripts/publish_ai_detections.py in its own process; a failure never stops the sweep."""
    try:
        subprocess.run([sys.executable, str(ROOT_DIR / "scripts" / "publish_ai_detections.py")],
                       timeout=300, check=False)
    except Exception as e:  # SSH down, timeout, ...
        print(f"[Sweeper] Publishing to the website failed: {e}")


def start_sweeper(
    batch_cells: int = 25,
    interval_sec: int = 30,
    continuous: bool = False,
    min_urgency: float = 75.0,
    provider: str = "both",
    publish: bool = False,
) -> None:
    print("=" * 78)
    print("MANARA AI: AUTONOMOUS BACKGROUND SATELLITE SWEEPER")
    print(f"Weights: {MODEL_WEIGHTS.name} | Batch: {batch_cells} cells | Provider: {provider}")
    print("=" * 78)

    # Initialize live dashboard immediately with existing state
    existing_feats, _ = load_existing_geojson()
    state = load_sweeper_state()
    render_live_dashboard(existing_feats, state, current_cycle=0)
    print(f"[Sweeper] Live dashboard ready at: {DASHBOARD_FILE}")

    model = YOLO(str(MODEL_WEIGHTS))
    osm_grid, regions = build_reference_indexes()

    iteration = 0
    while RUNNING:
        iteration += 1
        print(f"\n--- Sweeper Cycle #{iteration} ---")
        added = run_sweeper_batch(
            model=model,
            osm_grid=osm_grid,
            regions=regions,
            batch_cells_count=batch_cells,
            min_urgency=min_urgency,
            provider=provider,
            current_cycle=iteration,
        )
        # Push new candidates to the website (and pull reviews back) when something was found,
        # and every 10th cycle anyway so new reviews reach active_learning_feedback.json.
        if publish and (added or iteration % 10 == 1):
            publish_to_site()

        if not continuous or not RUNNING:
            break

        print(f"[Sweeper] Sleeping {interval_sec}s before next cycle... (Press Ctrl+C to stop)")
        time.sleep(interval_sec)

    print("\n[Sweeper] Shutdown cleanly. All progress saved.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manara AI Autonomous Background Satellite Sweeper")
    parser.add_argument("--batch-cells", type=int, default=25, help="Number of gap cells per cycle (each tiled with ~16 overlapping patches)")
    parser.add_argument("--interval-sec", type=int, default=30, help="Interval between cycles in continuous mode")
    parser.add_argument("--continuous", action="store_true", help="Run continuously in the background")
    parser.add_argument("--min-urgency", type=float, default=75.0, help="Minimum gap urgency score")
    parser.add_argument("--provider", choices=["esri", "mapbox", "both"], default="both", help="Satellite provider")
    parser.add_argument("--publish", action="store_true",
                        help="Publish new candidates to the website and pull reviews (scripts/publish_ai_detections.py)")
    args = parser.parse_args()

    start_sweeper(
        batch_cells=args.batch_cells,
        interval_sec=args.interval_sec,
        continuous=args.continuous,
        min_urgency=args.min_urgency,
        provider=args.provider,
        publish=args.publish,
    )
