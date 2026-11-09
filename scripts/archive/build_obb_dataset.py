"""
Builds YOLOv11-OBB (Oriented Bounding Box) Dataset & Colab Training Notebook
=============================================================================
Converts standard horizontal YOLO annotations into 8-coordinate oriented
bounding box labels (x1 y1 x2 y2 x3 y3 x4 y4) using Level 1 Roof-Boundary Snapping,
packages mosque_dataset_obb.zip, and generates train_yolov11x_obb_colab.ipynb.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from PIL import Image

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "scripts"))

from roof_boundary_snapping import snap_roof_boundary

SRC_DIR = ROOT_DIR / "poc_satellite_output" / "mosque_dataset_v2"
DST_DIR = ROOT_DIR / "poc_satellite_output" / "mosque_dataset_obb"
ZIP_PATH = ROOT_DIR / "poc_satellite_output" / "mosque_dataset_obb.zip"
COLAB_NB_PATH = ROOT_DIR / "poc_satellite_output" / "train_yolov11x_obb_colab.ipynb"


def process_single_sample(img_path: Path, lbl_path: Path, dst_img_dir: Path, dst_lbl_dir: Path) -> tuple[int, int]:
    """
    Processes one image/label pair.
    Returns:
        (num_boxes, is_negative_bool)
    """
    dst_img = dst_img_dir / img_path.name
    dst_lbl = dst_lbl_dir / lbl_path.name

    # Copy image
    if not dst_img.exists():
        try:
            # Use copyfile for reliability
            shutil.copyfile(img_path, dst_img)
        except Exception:
            return 0, 0

    if not lbl_path.exists():
        dst_lbl.write_text("", encoding="utf-8")
        return 0, 1

    txt = lbl_path.read_text(encoding="utf-8").strip()
    if not txt:
        # Hard negative
        dst_lbl.write_text("", encoding="utf-8")
        return 0, 1

    try:
        im = Image.open(img_path)
        w_img, h_img = im.size
    except Exception:
        dst_lbl.write_text("", encoding="utf-8")
        return 0, 1

    obb_lines = []
    for line in txt.splitlines():
        parts = line.strip().split()
        if len(parts) < 5:
            continue
        cls_id = int(parts[0])
        xc, yc, bw, bh = map(float, parts[1:5])

        x1 = (xc - bw / 2.0) * w_img
        y1 = (yc - bh / 2.0) * h_img
        x2 = (xc + bw / 2.0) * w_img
        y2 = (yc + bh / 2.0) * h_img

        snap_res = snap_roof_boundary(im, [x1, y1, x2, y2], lat=24.0)
        corners = snap_res["rotated_corners"]

        norm_coords = []
        for pt in corners:
            nx = min(1.0, max(0.0, pt[0] / w_img))
            ny = min(1.0, max(0.0, pt[1] / h_img))
            norm_coords.append(f"{nx:.6f} {ny:.6f}")

        obb_line = f"{cls_id} " + " ".join(norm_coords)
        obb_lines.append(obb_line)

    dst_lbl.write_text("\n".join(obb_lines) + "\n", encoding="utf-8")
    return len(obb_lines), 0


def build_obb_dataset():
    t0 = time.time()
    print("=" * 78)
    print("BUILDING YOLOV11-OBB ORIENTED BOUNDING BOX DATASET")
    print("=" * 78)

    if not SRC_DIR.exists():
        raise FileNotFoundError(f"Source dataset directory not found: {SRC_DIR}")

    # Prepare destination directories
    for split in ["train", "val"]:
        (DST_DIR / split / "images").mkdir(parents=True, exist_ok=True)
        (DST_DIR / split / "labels").mkdir(parents=True, exist_ok=True)

    total_boxes = 0
    total_samples = 0
    total_negs = 0

    for split in ["train", "val"]:
        src_img_dir = SRC_DIR / split / "images"
        src_lbl_dir = SRC_DIR / split / "labels"
        dst_img_dir = DST_DIR / split / "images"
        dst_lbl_dir = DST_DIR / split / "labels"

        img_files = sorted(src_img_dir.glob("*.jpg"))
        print(f"\n[OBB Builder] Converting {len(img_files)} {split} samples to oriented boxes...")

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = []
            for img_path in img_files:
                lbl_path = src_lbl_dir / f"{img_path.stem}.txt"
                futures.append(
                    executor.submit(process_single_sample, img_path, lbl_path, dst_img_dir, dst_lbl_dir)
                )

            for fut in as_completed(futures):
                b_count, is_neg = fut.result()
                total_boxes += b_count
                total_negs += is_neg
                total_samples += 1

        print(f"  -> Finished {split} split.")

    # Write dataset.yaml
    yaml_content = f"""# Ultralytics YOLOv11-OBB Dataset
path: mosque_dataset_obb
train: train/images
val: val/images

# Classes
names:
  0: mosque
"""
    (DST_DIR / "dataset.yaml").write_text(yaml_content, encoding="utf-8")
    print(f"\n[OBB Builder] Created dataset.yaml (1 class: 'mosque')")

    # Zip dataset
    print(f"\n[OBB Builder] Packaging archive: {ZIP_PATH}...")
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(DST_DIR):
            for file in files:
                file_path = Path(root) / file
                arcname = file_path.relative_to(DST_DIR.parent)
                zf.write(file_path, arcname)

    zip_size_mb = ZIP_PATH.stat().st_size / (1024 * 1024)
    elapsed = time.time() - t0
    print(f"[OBB Builder] Dataset zip ready ({zip_size_mb:.1f} MB) in {elapsed:.1f}s!")
    print(f"Summary: {total_samples} samples ({total_boxes} oriented mosque boxes, {total_negs} hard negatives).")

    generate_colab_notebook()


def generate_colab_notebook():
    print(f"\n[OBB Builder] Generating Colab training notebook: {COLAB_NB_PATH.name}...")

    nb_dict = {
        "nbformat": 4,
        "nbformat_minor": 0,
        "metadata": {
            "colab": {"name": "train_yolov11x_obb_colab.ipynb", "provenance": []},
            "accelerator": "GPU",
            "gpuClass": "standard",
            "language_info": {"name": "python"},
        },
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "# 🛰️ Manara AI: Train YOLOv11x-OBB (Oriented Bounding Box)\n",
                    "### Sub-Meter Satellite Mosque Architecture Detector with Wall-Aligned Orientation & Qibla Geometry\n",
                    "**Google Colab Edition (NVIDIA T4 / L4 / A100 GPU)**\n\n",
                    "---\n",
                    "### 📐 Architectural & GIS Advantage of OBB:\n",
                    "1. **Zero Corner Bloat**: Unlike horizontal bounding boxes (HBBO) that pad diagonal roofs with empty desert/street terrain, Oriented Bounding Boxes (OBB) rotate precisely to match wall perimeters.\n",
                    "2. **Dense Neighborhood Separation**: Eliminates Non-Maximum Suppression (NMS) false deletions where adjacent buildings or dense Medina alleyways overlap.\n",
                    "3. **Direct Geodesic Vectorization**: Output coordinates (x1, y1 ... x4, y4) can be inverse-projected from Qibla space directly to WGS84 polygon rings for 1-click OpenStreetMap (`building=mosque`) commits.\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# Step 1: Detect GPU & Install Ultralytics + ONNX Runtime\n",
                    "import torch\n",
                    "!nvidia-smi\n\n",
                    "gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'No GPU'\n",
                    "vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3) if torch.cuda.is_available() else 0\n",
                    "print(f'\\n Active GPU: {gpu_name} ({vram_gb:.1f} GB VRAM)')\n\n",
                    "if vram_gb < 16:\n",
                    "    print(' Recommended Batch Size: 8 (to avoid T4 CUDA OOM with 56.9M parameter YOLOv11x)')\n",
                    "else:\n",
                    "    print(' Recommended Batch Size: 16 (Optimal for A100 / L4)')\n\n",
                    "!pip install -q 'ultralytics>=8.3.0' onnx\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# Step 2: Extract & Verify Mosque OBB Dataset\n",
                    "import os\n",
                    "import zipfile\n",
                    "from pathlib import Path\n\n",
                    "# Optional Google Drive mount (Recommended: 10x faster than browser upload & preserves checkpoints)\n",
                    "try:\n",
                    "    from google.colab import drive\n",
                    "    if not os.path.exists('/content/drive'):\n",
                    "        drive.mount('/content/drive')\n",
                    "    if os.path.exists('/content/drive/MyDrive/mosque_dataset_obb.zip') and not os.path.exists('mosque_dataset_obb.zip'):\n",
                    "        print(' Found mosque_dataset_obb.zip in Google Drive! Copying to local NVMe...')\n",
                    "        !cp /content/drive/MyDrive/mosque_dataset_obb.zip /content/\n",
                    "except Exception as e:\n",
                    "    print('Drive check skipped or not mounted.')\n\n",
                    "if not os.path.exists('mosque_dataset_obb.zip'):\n",
                    "    print(' Please upload mosque_dataset_obb.zip via the Files sidebar on the left!')\n",
                    "    from google.colab import files\n",
                    "    uploaded = files.upload()\n\n",
                    "print(' Extracting mosque_dataset_obb.zip...')\n",
                    "with zipfile.ZipFile('mosque_dataset_obb.zip', 'r') as zip_ref:\n",
                    "    zip_ref.extractall('.')\n\n",
                    "# Guarantee robust absolute path in dataset.yaml\n",
                    "dataset_dir = Path('/content/mosque_dataset_obb').resolve()\n",
                    "yaml_path = dataset_dir / 'dataset.yaml'\n",
                    "yaml_content = f'''# Ultralytics YOLOv11-OBB Dataset\npath: {dataset_dir.as_posix()}\ntrain: train/images\nval: val/images\n\nnames:\n  0: mosque\n'''\n",
                    "yaml_path.write_text(yaml_content, encoding='utf-8')\n\n",
                    "train_count = len(list((dataset_dir / 'train' / 'images').glob('*.jpg')))\n",
                    "val_count = len(list((dataset_dir / 'val' / 'images').glob('*.jpg')))\n",
                    "print(f' Dataset Ready! Train: {train_count} images | Val: {val_count} images')\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# Step 3: Train YOLOv11x-OBB with GIS-Calibrated Augmentations\n",
                    "import torch\n",
                    "from ultralytics import YOLO\n\n",
                    "# Dynamic batch size based on available VRAM\n",
                    "vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3) if torch.cuda.is_available() else 0\n",
                    "batch_size = 16 if vram_gb >= 18 else 8\n",
                    "num_workers = 4 if vram_gb >= 18 else 2\n\n",
                    "print(f' Initializing YOLOv11x-OBB training on {torch.cuda.get_device_name(0)}')\n",
                    "print(f' Parameters: batch={batch_size}, workers={num_workers}, imgsz=640')\n\n",
                    "# Load pre-trained DOTA aerial weights\n",
                    "model = YOLO('yolo11x-obb.pt')\n\n",
                    "results = model.train(\n",
                    "    data='mosque_dataset_obb/dataset.yaml',\n",
                    "    task='obb',\n",
                    "    epochs=75,\n",
                    "    imgsz=640,\n",
                    "    batch=batch_size,\n",
                    "    workers=num_workers,\n",
                    "    lr0=0.005,\n",
                    "    lrf=0.01,           # Cosine final lr reaches 1% of lr0\n",
                    "    cos_lr=True,        # Smooth cosine learning rate decay\n",
                    "    patience=25,\n",
                    "    device=0,\n",
                    "    project='mosque_ai_obb',\n",
                    "    name='yolo11x_obb_run',\n",
                    "    exist_ok=True,      # Prevents incremental directory branching (yolo11x_obb_run2...)\n",
                    "    # GIS-Specific Geometric Inductive Biases:\n",
                    "    degrees=12.0,       # +/-12 deg realistic compass deviation for historical mosques\n",
                    "    fliplr=0.5,         # Lateral bilateral symmetry across the Qibla axis\n",
                    "    flipud=0.0,         # Disabled: strictly preserves forward Mihrab/Qibla vector\n",
                    "    scale=0.2,          # Handles Zoom-19 GSD variations (0.25 - 0.30 m/px across KSA latitudes)\n",
                    "    mosaic=1.0,         # Context mixing\n",
                    "    close_mosaic=10,    # Clean satellite tile fine-tuning in final 10 epochs\n",
                    "    plots=True,\n",
                    "    save=True,\n",
                    ")\n\n",
                    "print(f' Training complete! Best weights saved at: {results.save_dir}/weights/best.pt')\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# Step 4: Export to ONNX & Package Artifacts\n",
                    "import os\n",
                    "import shutil\n",
                    "from pathlib import Path\n",
                    "from google.colab import files\n",
                    "from ultralytics import YOLO\n\n",
                    "# 1. Locate run directory dynamically\n",
                    "run_dir = Path(results.save_dir) if ('results' in locals() and hasattr(results, 'save_dir')) else Path('mosque_ai_obb/yolo11x_obb_run')\n",
                    "best_pt = run_dir / 'weights' / 'best.pt'\n",
                    "print(f' Best weights found at: {best_pt}')\n\n",
                    "# 2. Export to high-speed ONNX runtime\n",
                    "print(' Exporting to ONNX format (opset 12)...')\n",
                    "try:\n",
                    "    best_model = YOLO(str(best_pt))\n",
                    "    best_model.export(format='onnx', opset=12, dynamic=True)\n",
                    "    best_onnx = run_dir / 'weights' / 'best.onnx'\n",
                    "    if best_onnx.exists():\n",
                    "        shutil.copy2(best_onnx, 'best_obb.onnx')\n",
                    "        print(' Successfully exported best_obb.onnx')\n",
                    "except Exception as e:\n",
                    "    print(f'ONNX export notice: {e}')\n\n",
                    "# 3. Copy top weights to root for immediate access\n",
                    "shutil.copy2(best_pt, 'best_obb.pt')\n\n",
                    "# 4. Package all metrics, PR curves, and weights into one clean archive\n",
                    "out_zip = 'Training_obb_results.zip'\n",
                    "shutil.make_archive('Training_obb_results', 'zip', run_dir)\n",
                    "print(f' Created {out_zip} ({Path(out_zip).stat().st_size / (1024*1024):.1f} MB)')\n\n",
                    "# 5. Backup to Google Drive if connected\n",
                    "if os.path.exists('/content/drive/MyDrive'):\n",
                    "    drive_dst = Path('/content/drive/MyDrive/Manara_OBB_Weights')\n",
                    "    drive_dst.mkdir(parents=True, exist_ok=True)\n",
                    "    shutil.copy2('best_obb.pt', drive_dst / 'best_obb.pt')\n",
                    "    shutil.copy2(out_zip, drive_dst / out_zip)\n",
                    "    if os.path.exists('best_obb.onnx'):\n",
                    "        shutil.copy2('best_obb.onnx', drive_dst / 'best_obb.onnx')\n",
                    "    print(f' Auto-saved copy directly to Google Drive: {drive_dst}')\n\n",
                    "# 6. Single trigger download\n",
                    "print(' Triggering download of best_obb.pt...')\n",
                    "files.download('best_obb.pt')\n",
                ],
            },
        ],
    }

    COLAB_NB_PATH.write_text(json.dumps(nb_dict, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OBB Builder] Colab notebook created at: {COLAB_NB_PATH}")


if __name__ == "__main__":
    build_obb_dataset()
