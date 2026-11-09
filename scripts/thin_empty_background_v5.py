"""
Thin out empty-looking background patches (sand, fields, bare land) in v5 train/val.

`build_dataset_v5.py` picks "urban" negatives near known mosques, but rural Saudi mosques
sit in open land, so ~37-41% of those negatives are still nearly empty. Once a model has
seen some sand it learns nothing from more of it, and those slots are better spent on
built-up confusers (villas, warehouses, schools).

Built-up score = share of pixels with a strong edge after light blur (roofs, walls, kerbs).
The threshold is the 5th percentile of the score on mosque patches. Background patches below
it are kept with probability KEEP_FRACTION; the rest are MOVED (not deleted) to
mosque_dataset_v5/_thinned/<split>/ and their manifest records to manifest_thinned.jsonl.
Test is never touched: it must mirror what the sweeper really scans.

    python scripts/thin_empty_background_v5.py            # apply
    python scripts/thin_empty_background_v5.py --dry-run
    python scripts/thin_empty_background_v5.py --restore  # undo
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "pipeline"))
from common import configure_utf8_output  # noqa: E402

configure_utf8_output()

D = ROOT_DIR / "poc_satellite_output" / "mosque_dataset_v5"
THIN = D / "_thinned"
MANIFEST = D / "manifest.jsonl"
THIN_MANIFEST = D / "manifest_thinned.jsonl"
KEEP_FRACTION = 0.30
THRESHOLD_PCT = 0.05
BG_KINDS = ("urban", "gap", "legacy_negative")
SPLITS = ("train", "val")


def builtup(path: Path) -> float:
    g = Image.open(path).convert("L").resize((256, 256)).filter(ImageFilter.GaussianBlur(1.2))
    a = np.asarray(g, dtype=float)
    gx = np.abs(np.diff(a, axis=1))[:-1]
    gy = np.abs(np.diff(a, axis=0))[:, :-1]
    return float((np.maximum(gx, gy) > 18).mean())


def load(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def save(path: Path, recs: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")


def restore() -> None:
    moved = load(THIN_MANIFEST)
    for r in moved:
        for sub, ext in (("images", "jpg"), ("labels", "txt")):
            src = THIN / r["split"] / sub / f"{r['id']}.{ext}"
            if src.exists():
                shutil.move(str(src), D / r["split"] / sub / src.name)
    save(MANIFEST, load(MANIFEST) + moved)
    THIN_MANIFEST.unlink(missing_ok=True)
    print(f"restored {len(moved)} patches")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--seed", type=int, default=20261108)
    args = ap.parse_args()
    if args.restore:
        return restore()
    if THIN_MANIFEST.exists():
        sys.exit("already thinned - run --restore first to re-thin")

    recs = load(MANIFEST)
    rng = random.Random(args.seed)
    pos = [r for r in recs if r["split"] == "train" and r["kind"] == "positive"]
    rng.shuffle(pos)
    ps = sorted(builtup(D / "train" / "images" / f"{r['id']}.jpg") for r in pos[:800])
    thr = ps[int(len(ps) * THRESHOLD_PCT)]
    print(f"threshold (mosque-patch p{int(THRESHOLD_PCT * 100)}): {thr:.4f}")

    keep, moved = [], []
    for r in sorted(recs, key=lambda x: x["id"]):
        if r["split"] in SPLITS and r["kind"] in BG_KINDS and r["n_labels"] == 0:
            r["builtup"] = round(builtup(D / r["split"] / "images" / f"{r['id']}.jpg"), 4)
            if r["builtup"] < thr and rng.random() >= KEEP_FRACTION:
                moved.append(r)
                continue
        keep.append(r)

    for sp in SPLITS:
        n_bg = sum(1 for r in keep if r["split"] == sp and r["n_labels"] == 0)
        n = sum(1 for r in keep if r["split"] == sp)
        print(f"  {sp}: moving {sum(1 for r in moved if r['split'] == sp)}, "
              f"left {n} patches ({n_bg} background = {n_bg / n:.0%})")
    if args.dry_run:
        return
    for r in moved:
        for sub, ext in (("images", "jpg"), ("labels", "txt")):
            dst = THIN / r["split"] / sub
            dst.mkdir(parents=True, exist_ok=True)
            shutil.move(str(D / r["split"] / sub / f"{r['id']}.{ext}"), dst / f"{r['id']}.{ext}")
    save(MANIFEST, keep)
    save(THIN_MANIFEST, moved)
    print(f"moved {len(moved)} patches to {THIN}")


if __name__ == "__main__":
    main()
