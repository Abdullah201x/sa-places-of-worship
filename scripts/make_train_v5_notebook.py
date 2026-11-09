"""Write poc_satellite_output/train_v5_obb_colab.ipynb (Colab training for dataset v5)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
NB_PATH = ROOT_DIR / "poc_satellite_output" / "train_v5_obb_colab.ipynb"


def md(src: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": src.strip("\n").splitlines(keepends=True)}


def code(src: str) -> dict:
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
            "source": src.strip("\n").splitlines(keepends=True)}


CELLS = [
    md("""
# Manara mosque detector v5 (YOLO11-OBB)

Trains on `mosque_dataset_v5.zip` built by `scripts/build_dataset_v5.py`:

* mosques at random positions in the patch (v1-v4 had 99% of labels at the exact centre)
* realistic background: inhabited neighbourhoods, sweeper gap cells, confirmed false positives
* only real footprints as labels (no synthetic prior boxes)
* **spatial** train / val / test split by 0.1° blocks (~10 km) - no tile leakage

Starts from the official DOTA-pretrained OBB weights, **not** from `best_obb.pt`
(that checkpoint has learned the centre bias we are trying to remove).

Runtime: A100 or L4 recommended. `yolo11l-obb` is the default - on a single-class task with ~10k
images it is within noise of `x`, trains ~2x faster and runs ~2x faster in the CPU sweeper.
"""),
    code("""
MODEL = 'yolo11l-obb.pt'   # or 'yolo11x-obb.pt'
EPOCHS = 80
IMGSZ = 640
!nvidia-smi -L
!pip install -q 'ultralytics>=8.3.0' onnx
"""),
    code("""
import os, zipfile, shutil
from pathlib import Path
try:
    from google.colab import drive
    drive.mount('/content/drive')
    src = Path('/content/drive/MyDrive/mosque_dataset_v5.zip')
    if src.exists() and not Path('mosque_dataset_v5.zip').exists():
        shutil.copy(src, 'mosque_dataset_v5.zip')
except Exception as e:
    print('Drive not mounted:', e)
if not Path('mosque_dataset_v5.zip').exists():
    from google.colab import files
    files.upload()
with zipfile.ZipFile('mosque_dataset_v5.zip') as z:
    z.extractall('/content')
ds = Path('/content/mosque_dataset_v5')
(ds / 'dataset.yaml').write_text(
    f"path: {ds}\\ntrain: train/images\\nval: val/images\\ntest: test/images\\nnames:\\n  0: mosque\\n")
for s in ('train', 'val', 'test'):
    imgs = list((ds / s / 'images').glob('*.jpg'))
    pos = sum(1 for p in (ds / s / 'labels').glob('*.txt') if p.read_text().strip())
    print(f'{s:<5} {len(imgs):>5} images, {pos:>5} with mosques, {len(imgs) - pos:>5} background')
"""),
    md("""
### Augmentation choices

* `degrees=5` - patches are Qibla-normalised, so prayer-hall walls are near-axis-aligned. That
  alignment is a real signal, so heavy rotation would throw it away. Small jitter covers
  imperfect orientation.
* `flipud=0`: an up/down flip would point the Qibla backwards. `fliplr=0.5` is fine because a
  left/right mirror keeps the Qibla pointing up.
* `translate=0.25` plus mosaic: extra positional variety, on top of the de-centred data.
* `scale=0.3`: ground resolution varies about 15% across Saudi latitudes and imagery sources.
"""),
    code("""
from ultralytics import YOLO
DRIVE_OUT = Path('/content/drive/MyDrive/Manara_v5')

def backup_weights(trainer):
    # Copy best.pt / last.pt to Drive after every save, so a disconnect cannot lose the run.
    if Path('/content/drive/MyDrive').exists():
        DRIVE_OUT.mkdir(exist_ok=True)
        for w in (trainer.best, trainer.last):
            if Path(w).exists():
                shutil.copy(w, DRIVE_OUT / Path(w).name)

model = YOLO(MODEL)
model.add_callback('on_model_save', backup_weights)
results = model.train(
    data='/content/mosque_dataset_v5/dataset.yaml', task='obb',
    epochs=EPOCHS, imgsz=IMGSZ, batch=-1, workers=8, device=0,
    optimizer='SGD', lr0=0.01, lrf=0.01, cos_lr=True, warmup_epochs=3,
    patience=25, close_mosaic=10,
    degrees=5.0, fliplr=0.5, flipud=0.0, translate=0.25, scale=0.3, mosaic=1.0,
    hsv_h=0.015, hsv_s=0.6, hsv_v=0.4,
    project='mosque_v5', name='obb', exist_ok=True, plots=True,
)
print('run dir:', model.trainer.save_dir)
"""),
    code("""
# Self-contained: also works after a kernel restart / reconnect (re-run cell 1 first for MODEL etc.).
import glob, shutil
from pathlib import Path
from ultralytics import YOLO
IMGSZ = 640
hits = sorted(glob.glob('/content/**/mosque_v5/obb/weights/best.pt', recursive=True))
if not hits and Path('/content/drive/MyDrive/Manara_v5/best.pt').exists():
    hits = ['/content/drive/MyDrive/Manara_v5/best.pt']
assert hits, 'best.pt not found - the runtime was reset, re-run training'
BEST = Path(hits[0]); RUN_DIR = BEST.parent.parent
print('using', BEST)

# Held-out TEST blocks (never seen during training or model selection)
best = YOLO(str(BEST))
m = best.val(data='/content/mosque_dataset_v5/dataset.yaml', split='test', imgsz=IMGSZ, plots=True)
print('test mAP50 =', round(m.box.map50, 4), ' mAP50-95 =', round(m.box.map, 4))
"""),
    code("""
best.export(format='onnx', opset=12, dynamic=True)
shutil.copy(BEST, '/content/best_v5_obb.pt')
shutil.make_archive('/content/Training_v5_results', 'zip', RUN_DIR)
if Path('/content/drive/MyDrive').exists():
    dst = Path('/content/drive/MyDrive/Manara_v5'); dst.mkdir(exist_ok=True)
    shutil.copy('/content/best_v5_obb.pt', dst); shutil.copy('/content/Training_v5_results.zip', dst)
from google.colab import files
files.download('/content/best_v5_obb.pt')
"""),
    md("""
Then locally, compare old and new models on the same held-out field test:

```
python scripts/eval_detector_v5.py --weights poc_satellite_output/best_obb.pt poc_satellite_output/best_v5_obb.pt
```

Pick the sweeper `conf_threshold` from that report (the F1 / FP-per-km² table), not from Ultralytics' curves.
"""),
]


def main() -> None:
    nb = {"cells": CELLS, "metadata": {"accelerator": "GPU", "colab": {"gpuType": "A100"},
                                        "kernelspec": {"name": "python3", "display_name": "Python 3"}},
          "nbformat": 4, "nbformat_minor": 5}
    NB_PATH.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {NB_PATH}")


if __name__ == "__main__":
    main()
