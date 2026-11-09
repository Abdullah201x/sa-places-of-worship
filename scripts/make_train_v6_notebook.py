"""Write poc_satellite_output/train_v6_obb_colab.ipynb (Colab training for dataset v6)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
NB_PATH = ROOT_DIR / "poc_satellite_output" / "train_v6_obb_colab.ipynb"


def md(src: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": src.strip("\n").splitlines(keepends=True)}


def code(src: str) -> dict:
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
            "source": src.strip("\n").splitlines(keepends=True)}


CELLS = [
    md("""
# 🛰️ Manara AI: Mosque Detector v6 (YOLO11-OBB)
### Deep Learning Architecture & Optimization Upgrades

Trains on `mosque_dataset_v6.zip` built by `scripts/build_dataset_v6.py`:

* **Relaxed Qibla Invariance**: ±10° crop frame jitter + ±15° rotation augmentation captures street-constrained and historical neighborhood mosques.
* **8x Hard Negative Mining**: Verified false positives from active learning oversampled 8x across random crops and rotations (~500 patches).
* **Uncertain Margin Learning**: 48 "unsure" active learning samples converted into hard margin background samples.
* **Native 512×512 Resolution**: Eliminates the 1.25x bilinear upsample blur of V5, keeping minaret shadows and domes razor-sharp.
* **Loss & Optimization Reform**: AdamW (`lr0=1e-3`), Cosine LR decay, and decoupled weight decay (`1e-2`) to prevent validation classification loss divergence on single-class aerial background.
* **Spatial Split**: Strict 0.1° geographic blocks (~10 km) preventing spatial leakage.

Runtime: NVIDIA A100 or L4 recommended (~40 min for 80 epochs).
`yolo11l-obb` is the default backbone (44M params, fast on VPS CPU sweeper via ONNX Runtime).
"""),
    code("""
MODEL = 'yolo11l-obb.pt'   # Primary candidate (or 'yolo11x-obb.pt')
EPOCHS = 80
IMGSZ = 512
!nvidia-smi -L
!pip install -q 'ultralytics>=8.3.0' onnx
"""),
    code("""
import os, zipfile, shutil
from pathlib import Path

# Mount Google Drive for persistent backup
try:
    from google.colab import drive
    drive.mount('/content/drive')
    src = Path('/content/drive/MyDrive/mosque_dataset_v6.zip')
    if src.exists() and not Path('mosque_dataset_v6.zip').exists():
        print('Found dataset in Google Drive, copying...')
        shutil.copy(src, 'mosque_dataset_v6.zip')
except Exception as e:
    print('Drive note:', e)

# Upload manually if not found in Drive
if not Path('mosque_dataset_v6.zip').exists():
    from google.colab import files
    print('Upload mosque_dataset_v6.zip:')
    files.upload()

with zipfile.ZipFile('mosque_dataset_v6.zip') as z:
    z.extractall('/content')

ds = Path('/content/mosque_dataset_v6')
(ds / 'dataset.yaml').write_text(
    f"path: {ds}\\ntrain: train/images\\nval: val/images\\ntest: test/images\\nnames:\\n  0: mosque\\n"
)

for s in ('train', 'val', 'test'):
    imgs = list((ds / s / 'images').glob('*.jpg'))
    pos = sum(1 for p in (ds / s / 'labels').glob('*.txt') if p.read_text().strip())
    print(f'{s:<5} {len(imgs):>5} images, {pos:>5} with mosques, {len(imgs) - pos:>5} background')
"""),
    md("""
### V6 Training Dynamics & Loss Formulation

* **Optimizer: AdamW** (`lr0=1e-3`, `lrf=0.05`, `weight_decay=1e-2`, `warmup_epochs=4`): Stabilizes gradient updates on single-class aerial patches and regularizes classification logits against overconfident memorization.
* **Scale-Preserving Augmentation**: `mosaic=0.3`, `close_mosaic=15`, `mixup=0.0`, `scale=0.2`, `degrees=15.0`.
* **Native 512×512**: Eliminates interpolation blur.
"""),
    code("""
from ultralytics import YOLO
from pathlib import Path
import shutil

DRIVE_OUT = Path('/content/drive/MyDrive/Manara_v6')

def backup_weights(trainer):
    # Copy best.pt / last.pt to Drive after every save, preventing loss on disconnect.
    if Path('/content/drive/MyDrive').exists():
        DRIVE_OUT.mkdir(exist_ok=True)
        for w in (trainer.best, trainer.last):
            if Path(w).exists():
                shutil.copy(w, DRIVE_OUT / Path(w).name)

model = YOLO(MODEL)
model.add_callback('on_model_save', backup_weights)

results = model.train(
    data='/content/mosque_dataset_v6/dataset.yaml',
    task='obb',
    epochs=EPOCHS,
    imgsz=IMGSZ,
    batch=-1,
    workers=8,
    device=0,
    optimizer='AdamW',
    lr0=1e-3,
    lrf=0.05,
    weight_decay=1e-2,
    warmup_epochs=4,
    cos_lr=True,
    patience=30,
    close_mosaic=15,
    degrees=15.0,
    fliplr=0.5,
    flipud=0.0,
    translate=0.20,
    scale=0.20,
    mosaic=0.30,
    mixup=0.0,
    hsv_h=0.015,
    hsv_s=0.6,
    hsv_v=0.4,
    project='mosque_v6',
    name='obb',
    exist_ok=True,
    plots=True,
)
print('Training finished. Results saved to:', model.trainer.save_dir)
"""),
    code("""
# Evaluation on held-out TEST split (zero geographic leakage)
import glob, shutil
from pathlib import Path
from ultralytics import YOLO

IMGSZ = 512
hits = sorted(glob.glob('/content/**/mosque_v6/obb/weights/best.pt', recursive=True))
if not hits and Path('/content/drive/MyDrive/Manara_v6/best.pt').exists():
    hits = ['/content/drive/MyDrive/Manara_v6/best.pt']
assert hits, 'best.pt not found - check training run directory'
BEST = Path(hits[0])
RUN_DIR = BEST.parent.parent
print('Using best checkpoint:', BEST)

best = YOLO(str(BEST))
metrics = best.val(data='/content/mosque_dataset_v6/dataset.yaml', split='test', imgsz=IMGSZ, plots=True)
print(f'Held-out Test mAP@50 = {metrics.box.map50:.4f}, mAP@50-95 = {metrics.box.map:.4f}')
"""),
    code("""
# Export ONNX and package deployment artifacts
best.export(format='onnx', opset=12, dynamic=True)
shutil.copy(BEST, '/content/best_v6_obb.pt')
shutil.make_archive('/content/Training_v6_results', 'zip', RUN_DIR)

if Path('/content/drive/MyDrive').exists():
    dst = Path('/content/drive/MyDrive/Manara_v6')
    dst.mkdir(exist_ok=True)
    shutil.copy('/content/best_v6_obb.pt', dst)
    shutil.copy('/content/Training_v6_results.zip', dst)
    print(f'Exported and backed up to {dst}')

from google.colab import files
files.download('/content/best_v6_obb.pt')
"""),
    md("""
### Production Verification Command (Local Machine)

After downloading `best_v6_obb.pt` to `poc_satellite_output/best_v6_obb.pt`, verify against the V6 Acceptance Gates:

```bash
# 1. Field-representative AP and radial off-center recall
python scripts/eval_detector_v5.py --weights poc_satellite_output/best_v5_obb.pt poc_satellite_output/best_v6_obb.pt --dataset poc_satellite_output/mosque_dataset_v6

# 2. Dual-provider sweeper cascade simulation
python scripts/eval_cascade_v5.py --weights poc_satellite_output/best_v6_obb.pt --split test
```
"""),
]


def main() -> None:
    nb = {
        "cells": CELLS,
        "metadata": {
            "accelerator": "GPU",
            "colab": {"gpuType": "A100"},
            "kernelspec": {"name": "python3", "display_name": "Python 3"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    NB_PATH.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {NB_PATH}")


if __name__ == "__main__":
    main()
