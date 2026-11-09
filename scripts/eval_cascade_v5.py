"""
Measure the sweeper's full detection cascade (stage 1 YOLO -> geographic NMS / dual-provider
merge -> stage 3 geometry guard -> stage 2 DINOv2 verifier -> provider rule) on v5 held-out data.

eval_detector_v5.py scores the YOLO model alone. The sweeper then filters its output again with
rules that were hand-tuned for the old centre-biased model. This script replays those rules
exactly as ai_background_sweeper.py applies them, so their effect can be measured and re-tuned.

* test split: every place is rendered on Esri AND Mapbox, so the sweeper's "dual-confirmed"
  logic is simulated faithfully (both providers' detections merged within 60 m).
* val split: one provider per place - use it to tune thresholds, then confirm on test.

Predictions and DINOv2 scores are cached in poc_satellite_output/eval_v5/, so re-running with
other rule settings is instant.

    python scripts/eval_cascade_v5.py --split val
    python scripts/eval_cascade_v5.py --split test
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
import time
from pathlib import Path

from PIL import Image

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "pipeline"))
sys.path.insert(0, str(ROOT_DIR / "scripts"))
from common import configure_utf8_output  # noqa: E402
from eval_detector_v5 import DATASET_DIR, REPORT_DIR, iou, patch_km2, poly  # noqa: E402
from stage3_geometric_guard import evaluate_geometry  # noqa: E402

configure_utf8_output()

PRED_CONF = 0.20      # cache everything above this; rules never go lower
NMS_M = 60.0          # apply_geographic_nms(min_distance_m=60.0)
IOU_THR = 0.3

# What ai_background_sweeper.py did before this evaluation
CURRENT = dict(t1=0.45, geom=(120.0, 2200.0, 2.2), s2=0.62, dual=0.60, single=0.68)
GEOMS = {"off": None, "current": (120.0, 2200.0, 2.2), "relaxed": (60.0, 6000.0, 3.5)}


def mpp(lat: float) -> float:
    return 156543.03392 * math.cos(math.radians(lat)) / 2**19


def load_recs(split: str) -> list[dict]:
    recs = [json.loads(l) for l in (DATASET_DIR / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    return [r for r in recs if r["split"] == split and (DATASET_DIR / split / "images" / f"{r['id']}.jpg").exists()]


def predict(weights: Path, recs: list[dict], split: str, imgsz: int = 512) -> dict:
    cache = REPORT_DIR / f"cascade_preds_{weights.stem}_{split}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    from ultralytics import YOLO

    model = YOLO(str(weights))
    out, t0 = {}, time.time()
    for i in range(0, len(recs), 8):
        chunk = recs[i : i + 8]
        imgs = [Image.open(DATASET_DIR / split / "images" / f"{r['id']}.jpg").convert("RGB") for r in chunk]
        for r, res in zip(chunk, model.predict(imgs, conf=PRED_CONF, imgsz=imgsz, verbose=False)):
            out[r["id"]] = [
                {"conf": float(c), "pts": [list(map(float, p)) for p in pts], "xyxy": list(map(float, bb))}
                for pts, c, bb in zip(res.obb.xyxyxyxy.tolist(), res.obb.conf.tolist(), res.obb.xyxy.tolist())
            ]
        print(f"  yolo {min(i + 8, len(recs))}/{len(recs)} ({(i + 8) / (time.time() - t0):.1f} img/s)", flush=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out), encoding="utf-8")
    return out


def dino_scores(weights: Path, recs: list[dict], preds: dict, split: str) -> None:
    """Attach the stage-2 verifier probability to every cached prediction (same crop as the sweeper)."""
    cache = REPORT_DIR / f"cascade_dino_{weights.stem}_{split}.json"
    scores = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    todo = [(r, k) for r in recs for k in range(len(preds[r["id"]])) if f"{r['id']}#{k}" not in scores]
    if todo:
        from stage2_verifier import verify_candidate_patch

        t0 = time.time()
        for n, (r, k) in enumerate(todo, 1):
            img = Image.open(DATASET_DIR / split / "images" / f"{r['id']}.jpg").convert("RGB")
            x1, y1, x2, y2 = [int(v) for v in preds[r["id"]][k]["xyxy"]]
            mx, my = max(10, int((x2 - x1) * 0.15)), max(10, int((y2 - y1) * 0.15))
            w, h = img.size
            crop = img.crop((max(0, x1 - mx), max(0, y1 - my), min(w, x2 + mx), min(h, y2 + my)))
            scores[f"{r['id']}#{k}"] = verify_candidate_patch(crop)["verifier_score"]
            if n % 200 == 0 or n == len(todo):
                print(f"  dino {n}/{len(todo)} ({n / (time.time() - t0):.1f}/s)", flush=True)
        cache.write_text(json.dumps(scores), encoding="utf-8")
    for r in recs:
        for k, p in enumerate(preds[r["id"]]):
            p["s2"] = scores[f"{r['id']}#{k}"]


def build_places(recs: list[dict], preds: dict) -> list[dict]:
    """A place = one frame on the ground; on test it has an Esri and a Mapbox rendering."""
    places: dict[str, dict] = {}
    for r in recs:
        base = r["id"][:-3] if r["id"].endswith("_mb") else r["id"]
        pl = places.setdefault(base, {"rec": r, "dets": []})
        if not r["id"].endswith("_mb"):
            pl["rec"] = r
        prov = "mapbox" if r["id"].endswith("_mb") else "esri"
        pl["dets"] += [dict(p, provider=prov) for p in preds[r["id"]]]
    return list(places.values())


def sweeper_nms(dets: list[dict], t1: float, lat: float) -> list[dict]:
    """Replica of scan_worship_gaps.apply_geographic_nms on stage-1 survivors (conf >= t1)."""
    r_px = NMS_M / mpp(lat)
    kept: list[dict] = []
    for d in sorted((d for d in dets if d["conf"] >= t1), key=lambda d: -d["conf"]):
        cx, cy = sum(p[0] for p in d["pts"]) / 4, sum(p[1] for p in d["pts"]) / 4
        hit = next((k for k in kept if (k["cx"] - cx) ** 2 + (k["cy"] - cy) ** 2 <= r_px * r_px), None)
        if hit is None:
            kept.append(dict(d, cx=cx, cy=cy, dual=False))
        elif hit["provider"] != d["provider"]:
            hit["dual"] = True
            hit["conf"] = round(min(0.99, max(hit["conf"], d["conf"]) + 0.03), 3)
    return kept


def passes(d: dict, lat: float, cfg: dict) -> bool:
    if cfg["geom"] is not None:
        lo, hi, asp = cfg["geom"]
        if not evaluate_geometry(d["xyxy"], lat, min_area_m2=lo, max_area_m2=hi, max_aspect_ratio=asp)["is_valid"]:
            return False
    if d["s2"] < cfg["s2"]:
        return False
    return d["conf"] >= (cfg["dual"] if d["dual"] else cfg["single"])


def score(places: list[dict], cfg: dict) -> dict:
    tp = fp = fp_bg = 0
    n_gt = sum(len(p["rec"]["labels_px"]) for p in places)
    bg_km2 = 0.0
    lost = {"geom": 0, "s2": 0, "rule": 0}
    for pl in places:
        rec = pl["rec"]
        is_bg = not rec["labels_px"]
        bg_km2 += patch_km2(rec["lat"]) if is_bg else 0.0
        gts = [poly(g) for g in rec["labels_px"]]
        used = [False] * len(gts)
        for d in sweeper_nms(pl["dets"], cfg["t1"], rec["lat"]):
            p = poly(d["pts"])
            best, bj = 0.0, -1
            for j, g in enumerate(gts):
                if not used[j] and (v := iou(p, g)) > best:
                    best, bj = v, j
            is_tp = best >= IOU_THR
            if not passes(d, rec["lat"], cfg):
                if is_tp:  # attribute the lost mosque to the first rule that killed it
                    g = cfg["geom"]
                    if g and not evaluate_geometry(d["xyxy"], rec["lat"], min_area_m2=g[0], max_area_m2=g[1],
                                                   max_aspect_ratio=g[2])["is_valid"]:
                        lost["geom"] += 1
                    elif d["s2"] < cfg["s2"]:
                        lost["s2"] += 1
                    else:
                        lost["rule"] += 1
                continue
            if is_tp:
                used[bj] = True
                tp += 1
            else:
                fp += 1
                fp_bg += is_bg
    p, r = tp / max(tp + fp, 1), tp / max(n_gt, 1)
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / max(p + r, 1e-9), 3),
            "fp_per_km2_bg": round(fp_bg / max(bg_km2, 1e-9), 2), "tp": tp, "fp": fp, "n_gt": n_gt,
            "mosques_lost_to": lost}


def fmt(name: str, s: dict) -> str:
    l = s["mosques_lost_to"]
    return (f"  {name:<44} P {s['precision']:.3f}  R {s['recall']:.3f}  F1 {s['f1']:.3f}  "
            f"FP/km2 {s['fp_per_km2_bg']:>5.2f}   lost: geom {l['geom']:>3} dino {l['s2']:>3} rule {l['rule']:>3}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default=str(ROOT_DIR / "poc_satellite_output" / "best_v5_obb.pt"))
    ap.add_argument("--split", default="test", choices=("val", "test"))
    ap.add_argument("--imgsz", type=int, default=512)
    ap.add_argument("--dataset", type=str, default=None)
    args = ap.parse_args()
    w = Path(args.weights)

    if args.dataset:
        global DATASET_DIR
        DATASET_DIR = Path(args.dataset)

    recs = load_recs(args.split)
    print(f"{len(recs)} {args.split} patches")
    preds = predict(w, recs, args.split, imgsz=args.imgsz)
    dino_scores(w, recs, preds, args.split)
    places = build_places(recs, preds)
    print(f"{len(places)} places, {sum(len(p['rec']['labels_px']) for p in places)} mosques\n")

    report = {"weights": w.name, "split": args.split, "rows": {}}

    def row(name, cfg):
        s = score(places, cfg)
        report["rows"][name] = {"cfg": cfg, **s}
        print(fmt(name, s))
        return s

    print("Stage 1 only (YOLO + NMS/dual merge, no extra filters):")
    for t in (0.25, 0.35, 0.45, 0.55, 0.65):
        row(f"yolo>={t}", dict(t1=t, geom=None, s2=0.0, dual=t, single=t))

    print("\nCascade as it was in the sweeper, and with one filter removed at a time:")
    row("current cascade", CURRENT)
    row("  - without geometry guard", dict(CURRENT, geom=None))
    row("  - without DINOv2 verifier", dict(CURRENT, s2=0.0))
    row("  - without single/dual rule", dict(CURRENT, dual=CURRENT["t1"], single=CURRENT["t1"]))

    print("\nGrid search (best F1):")
    grid = []
    for t1, g, s2, extra in itertools.product((0.30, 0.35, 0.40, 0.45, 0.50), GEOMS, (0.0, 0.3, 0.5, 0.62),
                                              (0.0, 0.05, 0.10, 0.15, 0.20)):
        cfg = dict(t1=t1, geom=GEOMS[g], s2=s2, dual=t1, single=round(t1 + extra, 2))
        grid.append((score(places, cfg), g, cfg))
    grid.sort(key=lambda x: -x[0]["f1"])
    for s, g, cfg in grid[:8]:
        print(fmt(f"t1={cfg['t1']} single={cfg['single']} dino>={cfg['s2']} geom={g}", s))
    report["grid_top"] = [{"geom": g, "cfg": cfg, **s} for s, g, cfg in grid[:25]]

    out = REPORT_DIR / f"cascade_{w.stem}_{args.split}.json"
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\nsaved {out}")


if __name__ == "__main__":
    main()
