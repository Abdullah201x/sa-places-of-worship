"""
Field-representative evaluation of a mosque detector on the v5 held-out split.

Ultralytics' built-in val reports mAP on whatever split you give it. This script adds the
numbers that decide whether the sweeper is useful:

* recall vs. distance of the mosque from the patch centre  -> exposes centre bias
* false positives per km^2 on realistic background         -> what a reviewer will see
  (urban neighbourhoods, gap cells, confirmed past FPs, legacy hard negatives)
* precision / recall / F1 at each confidence threshold      -> pick the sweeper threshold

Matching: a prediction is a true positive if its oriented polygon has IoU >= --iou with an
unmatched ground-truth footprint (default 0.3 - OSM footprints and Esri imagery can be
offset by a few metres, so 0.5 punishes registration error, not the detector).

Note: "false positives" on gap-cell patches are an upper bound - some may be genuinely
unmapped mosques, which is exactly what the sweeper is hunting for.

Usage:
    python scripts/eval_detector_v5.py --weights poc_satellite_output/best_obb.pt
    python scripts/eval_detector_v5.py --weights a.pt b.pt --split val
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import sys
import time
from pathlib import Path

from PIL import Image
from shapely.geometry import Polygon

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "pipeline"))
from common import configure_utf8_output  # noqa: E402

configure_utf8_output()

DATASET_DIR = ROOT_DIR / "poc_satellite_output" / "mosque_dataset_v6"
if not DATASET_DIR.exists():
    DATASET_DIR = ROOT_DIR / "poc_satellite_output" / "mosque_dataset_v5"
REPORT_DIR = ROOT_DIR / "poc_satellite_output" / "eval_v5"
THRESHOLDS = [0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85]
OFFSET_BUCKETS = [(0, 60), (60, 120), (120, 180), (180, 400)]  # px from centre (~0.27 m/px)
BACKGROUND_KINDS = ("urban", "gap", "confirmed_fp", "legacy_negative", "unsure_negative")


def patch_km2(lat: float) -> float:
    mpp = 156543.03392 * math.cos(math.radians(lat)) / 2**19
    return (512 * mpp / 1000.0) ** 2


def poly(pts) -> Polygon:
    return Polygon(pts).buffer(0)


def iou(a: Polygon, b: Polygon) -> float:
    inter = a.intersection(b).area
    return inter / max(a.union(b).area, 1e-6)


def predict_all(weights: Path, recs: list[dict], split: str, imgsz: int, batch: int) -> dict[str, list]:
    import os
    import torch
    from ultralytics import YOLO

    torch.set_num_threads(min(12, os.cpu_count() or 6))
    model = YOLO(str(weights))
    out: dict[str, list] = {}
    t0 = time.time()
    for i in range(0, len(recs), batch):
        chunk = recs[i : i + batch]
        imgs = [Image.open(DATASET_DIR / split / "images" / f"{r['id']}.jpg").convert("RGB") for r in chunk]
        results = model.predict(imgs, conf=0.05, imgsz=imgsz, verbose=False)
        for r, res in zip(chunk, results):
            preds = []
            if getattr(res, "obb", None) is not None and len(res.obb):
                for pts, c in zip(res.obb.xyxyxyxy.tolist(), res.obb.conf.tolist()):
                    preds.append((float(c), [tuple(p) for p in pts]))
            elif res.boxes is not None:
                for (x0, y0, x1, y1), c in zip(res.boxes.xyxy.tolist(), res.boxes.conf.tolist()):
                    preds.append((float(c), [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]))
            out[r["id"]] = preds
        done = min(i + batch, len(recs))
        print(f"    {weights.name}: {done}/{len(recs)} ({done / max(time.time() - t0, 1e-6):.2f} img/s)", flush=True)
    return out


def match(recs, preds, iou_thr):
    """Return per-prediction rows (conf, is_tp, rec_id) and per-GT rows (rec, gt_idx, best_conf_matched)."""
    pred_rows, gt_hits = [], {}
    for r in recs:
        gts = [poly(g) for g in r["labels_px"]]
        used = [False] * len(gts)
        for conf, pts in sorted(preds.get(r["id"], []), key=lambda x: -x[0]):
            p = poly(pts)
            best, bj = 0.0, -1
            for j, g in enumerate(gts):
                if not used[j]:
                    v = iou(p, g)
                    if v > best:
                        best, bj = v, j
            if best >= iou_thr:
                used[bj] = True
                gt_hits[(r["id"], bj)] = conf
                pred_rows.append((conf, True, r["id"]))
            else:
                pred_rows.append((conf, False, r["id"]))
    return pred_rows, gt_hits


def average_precision(pred_rows, n_gt) -> float:
    rows = sorted(pred_rows, key=lambda x: -x[0])
    tp = fp = 0
    prec, rec = [], []
    for _, is_tp, _ in rows:
        tp += is_tp
        fp += not is_tp
        prec.append(tp / (tp + fp))
        rec.append(tp / max(n_gt, 1))
    # all-point interpolation
    ap, prev_r = 0.0, 0.0
    for k in range(len(prec)):
        p_interp = max(prec[k:])
        ap += (rec[k] - prev_r) * p_interp
        prev_r = rec[k]
    return ap


def evaluate(weights: Path, split: str, iou_thr: float, imgsz: int, batch: int, limit: int | None,
             provider: str | None = None) -> dict:
    recs = [json.loads(l) for l in (DATASET_DIR / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    recs = [r for r in recs if r["split"] == split and (DATASET_DIR / split / "images" / f"{r['id']}.jpg").exists()]
    if provider:
        recs = [r for r in recs if r.get("provider", "esri") == provider]
    if limit:
        recs = recs[:limit]
    print(f"  {len(recs)} {split} patches")
    preds = predict_all(weights, recs, split, imgsz, batch)
    pred_rows, gt_hits = match(recs, preds, iou_thr)
    by_id = {r["id"]: r for r in recs}
    n_gt = sum(len(r["labels_px"]) for r in recs)

    report = {"weights": str(weights), "split": split, "iou": iou_thr, "n_patches": len(recs), "n_gt": n_gt,
              "AP": round(average_precision(pred_rows, n_gt), 4), "thresholds": [], "recall_by_offset": {},
              "fp_per_km2_by_kind": {}}

    bg = [r for r in recs if r["kind"] in BACKGROUND_KINDS and not r["labels_px"]]
    bg_km2 = sum(patch_km2(r["lat"]) for r in bg)
    for t in THRESHOLDS:
        tp = sum(1 for c, ok, _ in pred_rows if ok and c >= t)
        fp = sum(1 for c, ok, _ in pred_rows if not ok and c >= t)
        fp_bg = sum(1 for c, ok, rid in pred_rows if not ok and c >= t and rid in {r["id"] for r in bg})
        p = tp / max(tp + fp, 1)
        rc = tp / max(n_gt, 1)
        report["thresholds"].append({
            "conf": t, "precision": round(p, 3), "recall": round(rc, 3),
            "f1": round(2 * p * rc / max(p + rc, 1e-9), 3),
            "fp_per_km2_background": round(fp_bg / max(bg_km2, 1e-9), 2),
            "bg_patches_with_any_fp": round(
                sum(1 for r in bg if any(c >= t for c, _ in preds.get(r["id"], []))) / max(len(bg), 1), 3),
        })

    # Centre-bias probe: recall of the *target* mosque in positive patches, by offset from centre.
    for t in (0.25, 0.45, 0.65):
        row = {}
        for lo, hi in OFFSET_BUCKETS:
            sel = [r for r in recs if r["kind"] == "positive" and lo <= r.get("target_offset_px", -1) < hi]
            hit = 0
            for r in sel:
                j = r["fids"].index(r["target"])
                hit += gt_hits.get((r["id"], j), -1) >= t
            row[f"{lo}-{hi}px"] = {"n": len(sel), "recall": round(hit / max(len(sel), 1), 3)}
        report["recall_by_offset"][str(t)] = row

    for kind in BACKGROUND_KINDS:
        sel = [r for r in bg if r["kind"] == kind]
        km2 = sum(patch_km2(r["lat"]) for r in sel)
        report["fp_per_km2_by_kind"][kind] = {
            "n_patches": len(sel),
            **{str(t): round(sum(1 for r in sel for c, _ in preds.get(r["id"], []) if c >= t) / max(km2, 1e-9), 1)
               for t in (0.25, 0.45, 0.65)},
        }

    # Per imagery provider (test split is rendered from both providers at identical places)
    report["by_provider"] = {}
    for prov in sorted({r.get("provider", "esri") for r in recs}):
        ids = {r["id"] for r in recs if r.get("provider", "esri") == prov}
        rows = [x for x in pred_rows if x[2] in ids]
        ngt = sum(len(r["labels_px"]) for r in recs if r["id"] in ids)
        bgp = [r for r in bg if r["id"] in ids]
        km2 = sum(patch_km2(r["lat"]) for r in bgp)
        entry = {"n_patches": len(ids), "n_gt": ngt, "AP": round(average_precision(rows, ngt), 4)}
        for t in (0.25, 0.45, 0.65):
            tp = sum(1 for c, ok, _ in rows if ok and c >= t)
            fp = sum(1 for c, ok, _ in rows if not ok and c >= t)
            fpb = sum(1 for r in bgp for c, _ in preds.get(r["id"], []) if c >= t)
            entry[str(t)] = {"precision": round(tp / max(tp + fp, 1), 3), "recall": round(tp / max(ngt, 1), 3),
                             "fp_per_km2_background": round(fpb / max(km2, 1e-9), 1)}
        report["by_provider"][prov] = entry

    # Recall by region (target mosques only, conf >= 0.45)
    reg = collections.defaultdict(lambda: [0, 0])
    for r in recs:
        if r["kind"] == "positive":
            j = r["fids"].index(r["target"])
            reg[r.get("region", "?")][0] += 1
            reg[r.get("region", "?")][1] += gt_hits.get((r["id"], j), -1) >= 0.45
    report["recall_by_region@0.45"] = {k: {"n": n, "recall": round(h / n, 3)} for k, (n, h) in sorted(reg.items())}
    return report


def print_report(rep: dict) -> None:
    print(f"\n=== {Path(rep['weights']).name} on v5/{rep['split']} — {rep['n_patches']} patches, {rep['n_gt']} mosques,"
          f" AP@IoU{rep['iou']} = {rep['AP']:.3f}")
    print(f"  {'conf':>5} {'prec':>6} {'recall':>7} {'F1':>6} {'FP/km2 bg':>10} {'bg patches w/ FP':>17}")
    for t in rep["thresholds"]:
        print(f"  {t['conf']:>5.2f} {t['precision']:>6.3f} {t['recall']:>7.3f} {t['f1']:>6.3f}"
              f" {t['fp_per_km2_background']:>10.1f} {t['bg_patches_with_any_fp']:>17.1%}")
    print("  target-mosque recall by distance from patch centre (centre-bias probe):")
    for t, row in rep["recall_by_offset"].items():
        cells = "  ".join(f"{k}: {v['recall']:.2f} (n={v['n']})" for k, v in row.items())
        print(f"    conf>={t}: {cells}")
    if len(rep.get("by_provider", {})) > 1:
        print("  by imagery provider (precision / recall / FP per km^2 background):")
        for prov, e in rep["by_provider"].items():
            cells = "  ".join(f"@{t}: {e[t]['precision']:.2f}/{e[t]['recall']:.2f}/{e[t]['fp_per_km2_background']}"
                              for t in ("0.25", "0.45", "0.65"))
            print(f"    {prov:<7} n={e['n_patches']:<4} AP={e['AP']:.3f}  {cells}")
    print("  FP per km^2 by background type (conf 0.25 / 0.45 / 0.65):")
    for k, v in rep["fp_per_km2_by_kind"].items():
        print(f"    {k:<16} n={v['n_patches']:<4} {v['0.25']:>7} {v['0.45']:>7} {v['0.65']:>7}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", nargs="+", required=True)
    ap.add_argument("--split", default="test", choices=["train", "val", "test"])
    ap.add_argument("--iou", type=float, default=0.3)
    ap.add_argument("--imgsz", type=int, default=512)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--provider", choices=["esri", "mapbox"], default=None, help="restrict to one provider")
    ap.add_argument("--dataset", type=str, default=None, help="path to dataset dir (defaults to mosque_dataset_v6 or v5)")
    args = ap.parse_args()

    global DATASET_DIR
    if args.dataset:
        DATASET_DIR = Path(args.dataset)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    for w in args.weights:
        wp = Path(w)
        rep = evaluate(wp, args.split, args.iou, args.imgsz, args.batch, args.limit, args.provider)
        print_report(rep)
        out = REPORT_DIR / f"{wp.stem}_{args.split}{'_' + args.provider if args.provider else ''}.json"
        out.write_text(json.dumps(rep, indent=2), encoding="utf-8")
        print(f"  saved {out}")


if __name__ == "__main__":
    main()
