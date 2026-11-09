import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "scripts"))

from ai_background_sweeper import load_sweeper_state, render_live_dashboard
from build_overlays import build_all_overlays

fb_path = ROOT_DIR / "active_learning_feedback.json"
geojson_path = ROOT_DIR / "ai_detected_mosques_sa.geojson"

with open(fb_path, 'r', encoding='utf-8') as f:
    fb = json.load(f)

neg_ids = {k for k, v in fb.items() if v.get('status') == 'negative'}
pos_ids = {k for k, v in fb.items() if v.get('status') == 'positive'}

with open(geojson_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

features = data.get("features", [])
print(f"Initial features in GeoJSON: {len(features)}")

# Filter out explicitly rejected items
clean_features = []
purged_count = 0

for ft in features:
    det_id = ft["properties"].get("detection_id")
    if det_id in neg_ids:
        purged_count += 1
        continue
    if det_id in pos_ids:
        ft["properties"]["human_verified"] = True
    clean_features.append(ft)

print(f"Purged {purged_count} human-rejected false positives.")
print(f"Remaining verified features: {len(clean_features)}")

data["features"] = clean_features
data["metadata"]["total_detected_mosques"] = len(clean_features)
data["metadata"]["human_reviewed_count"] = len(fb)

with open(geojson_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

# Update sweeper_state.json
state = load_sweeper_state()
state["total_detections_found"] = len(clean_features)
with open(ROOT_DIR / "poc_satellite_output" / "sweeper_state.json", "w", encoding="utf-8") as f:
    json.dump(state, f, indent=2)

# Re-render dashboard
render_live_dashboard(clean_features, state, current_cycle=0)
print("Live dashboard re-rendered!")

# Rebuild PMTiles overlays
build_all_overlays()
print("Overlays rebuilt!")
