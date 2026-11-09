"""
Publish the sweeper's AI mosque candidates to the live site and pull the reviews back.

    python scripts/publish_ai_detections.py              # push detections, then pull reviews
    python scripts/publish_ai_detections.py --pull-only  # only pull reviews
    python scripts/publish_ai_detections.py --dry-run    # build the payload, print a summary

Push: ai_detected_mosques_sa.geojson -> slim JSON (no thumbnails; the footprint is converted from
patch pixels to lon/lat) -> `ssh user@host docker exec -i <api> python -m app.ai_sync import`.
The site shows them to OSM users on MANARA_SUGGESTIONS_ALLOWLIST, who mark each one
"mosque" / "not a mosque" / "unsure".

Pull: `python -m app.ai_sync reviews` -> ai_site_reviews.json (raw tallies), and every reviewed
detection that has no local verdict yet is added to active_learning_feedback.json with
"source": "site", so build_dataset_v5.py uses it (negatives become confirmed_fp hard negatives).
Local verdicts are never overwritten.

Uses the SSH access already used for maintenance, so there is no public write API and no extra
secret. Set MANARA_VPS (user@host) and MANARA_API_CONTAINER (the API container name) to point at your server.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "pipeline"))
sys.path.insert(0, str(ROOT_DIR / "scripts"))
from common import configure_utf8_output  # noqa: E402

configure_utf8_output()

DETECTIONS = ROOT_DIR / "ai_detected_mosques_sa.geojson"
FEEDBACK = ROOT_DIR / "active_learning_feedback.json"
SITE_REVIEWS = ROOT_DIR / "ai_site_reviews.json"
VPS = os.environ.get("MANARA_VPS", "")
API_CONTAINER = os.environ.get("MANARA_API_CONTAINER", "")
ZOOM, PATCH = 19, 512


def _truthy(v) -> bool:
    return v is True or str(v).strip().lower() in ("true", "1", "yes")


def footprint_lonlat(props: dict, lat: float, lon: float) -> list[list[float]] | None:
    """Rotated box corners (Qibla-rotated patch pixels) -> [[lon, lat], ...] on the ground.

    The detection point is the box centre, so each corner is placed by its offset from the
    centre with the same inverse rotation the sweeper used for the point itself."""
    from scan_worship_gaps import rotated_patch_px_to_latlon

    corners = props.get("rotated_corners")
    if isinstance(corners, str):
        try:
            corners = json.loads(corners)
        except ValueError:
            return None
    if not corners or len(corners) != 4:
        return None
    qibla = float(props.get("qibla_bearing") or 0.0)
    cx = sum(p[0] for p in corners) / 4
    cy = sum(p[1] for p in corners) / 4
    ring = []
    for px, py in corners:
        la, lo = rotated_patch_px_to_latlon(PATCH / 2 + (px - cx), PATCH / 2 + (py - cy), lat, lon, qibla, ZOOM, PATCH)
        ring.append([round(lo, 7), round(la, 7)])
    return ring


def build_payload() -> dict:
    feats = json.loads(DETECTIONS.read_text(encoding="utf-8")).get("features", [])
    out = []
    for f in feats:
        p = f.get("properties") or {}
        g = f.get("geometry") or {}
        if g.get("type") != "Point" or not p.get("detection_id"):
            continue
        lon, lat = (float(v) for v in g["coordinates"][:2])
        area = p.get("est_area_m2")
        out.append({
            "id": p["detection_id"],
            "lat": lat,
            "lon": lon,
            "confidence": float(p.get("confidence") or 0.0),
            "dual": _truthy(p.get("cross_verified")),
            "footprint": footprint_lonlat(p, lat, lon),
            "region_code": p.get("region_code") or None,
            "region_name": p.get("region_name") or None,
            "qibla": float(p["qibla_bearing"]) if p.get("qibla_bearing") not in (None, "") else None,
            "area_m2": float(area) if area not in (None, "", 0, "0") else None,
            "model": p.get("model_weights") or None,
        })
    return {"detections": out}


def ssh_ai_sync(command: str, stdin: str | None = None) -> dict:
    if not VPS or not API_CONTAINER:
        raise SystemExit("Set MANARA_VPS (user@host) and MANARA_API_CONTAINER before publishing or pulling reviews.")
    cmd = ["ssh", "-o", "BatchMode=yes", VPS, f"docker exec -i {API_CONTAINER} python -m app.ai_sync {command}"]
    res = subprocess.run(cmd, input=stdin, capture_output=True, text=True, encoding="utf-8", timeout=180)
    if res.returncode != 0:
        raise RuntimeError(f"ai_sync {command} failed ({res.returncode}): {res.stderr.strip()[-800:]}")
    return json.loads(res.stdout)


def site_status(t: dict) -> str:
    if t["n_positive"] > t["n_negative"]:
        return "positive"
    if t["n_negative"] > t["n_positive"]:
        return "negative"
    return "unsure"


def merge_reviews(reviews: dict) -> tuple[int, int]:
    SITE_REVIEWS.write_text(json.dumps(reviews, ensure_ascii=False, indent=1), encoding="utf-8")
    fb = json.loads(FEEDBACK.read_text(encoding="utf-8")) if FEEDBACK.exists() else {}
    added = updated = 0
    for det_id, t in reviews.items():
        cur = fb.get(det_id)
        if cur is not None and cur.get("source") != "site":
            continue  # a local verdict always wins
        entry = {
            "status": site_status(t), "source": "site", "lat": t["lat"], "lon": t["lon"],
            "region_code": t.get("region_code") or "", "confidence": t.get("confidence"),
            "site_votes": {k: t[k] for k in ("n_positive", "n_negative", "n_unsure")},
            "footprint_lonlat": t.get("footprint"),
        }
        if cur is None:
            added += 1
        elif cur != entry:
            updated += 1
        fb[det_id] = entry
    FEEDBACK.write_text(json.dumps(fb, ensure_ascii=False, indent=2), encoding="utf-8")
    return added, updated


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pull-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.pull_only:
        payload = build_payload()
        dets = payload["detections"]
        print(f"{len(dets)} detections ({sum(d['dual'] for d in dets)} dual-provider, "
              f"{sum(d['footprint'] is not None for d in dets)} with footprint)")
        if args.dry_run:
            print(json.dumps(dets[:2], ensure_ascii=False, indent=1))
            return
        res = ssh_ai_sync("import", json.dumps(payload, ensure_ascii=False))
        print(f"published: {res['upserted']} upserted, {res['retired']} retired, {res['active']} live on the site")

    reviews = ssh_ai_sync("reviews")
    added, updated = merge_reviews(reviews)
    by = {s: sum(1 for t in reviews.values() if site_status(t) == s) for s in ("positive", "negative", "unsure")}
    print(f"site reviews: {len(reviews)} detections reviewed ({by['positive']} mosque, {by['negative']} not, "
          f"{by['unsure']} unsure) -> feedback +{added} new, {updated} updated")


if __name__ == "__main__":
    main()
