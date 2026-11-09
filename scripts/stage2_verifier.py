"""
Stage 2: Deep Vision Verifier with DINOv2
=========================================
Extracts 384-dimensional visual foundation embeddings from building crops,
comparing candidate patches against reference centroids of verified Saudi
mosques versus common satellite confusors (schools, villas, warehouses, sheds).
"""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

ROOT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT_DIR / "poc_satellite_output"
PROTOTYPES_PATH = OUTPUT_DIR / "verifier_prototypes.pt"

# Global model cache to avoid reloading on every cycle
_DINO_MODEL = None
_PROTOTYPES = None


def get_dino_model(device: str = "cpu"):
    global _DINO_MODEL
    if _DINO_MODEL is None:
        # Load cached DINOv2-Small from torch hub
        _DINO_MODEL = torch.hub.load(
            "facebookresearch/dinov2",
            "dinov2_vits14",
            pretrained=True,
            verbose=False,
        )
        _DINO_MODEL.to(device)
        _DINO_MODEL.eval()
    return _DINO_MODEL


def preprocess_crop(img_crop: Image.Image) -> torch.Tensor:
    """Preprocess image crop for DINOv2 (224x224, ImageNet normalization)."""
    img_crop = img_crop.convert("RGB").resize((224, 224), Image.Resampling.BILINEAR)
    arr = np.array(img_crop, dtype=np.float32) / 255.0
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    arr = (arr - mean) / std
    tensor = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0)
    return tensor


@torch.no_grad()
def extract_embedding(img_crop: Image.Image, model=None, device="cpu") -> np.ndarray:
    if model is None:
        model = get_dino_model(device)
    tensor = preprocess_crop(img_crop).to(device)
    feat = model(tensor)
    norm_feat = F.normalize(feat, p=2, dim=-1)
    return norm_feat.squeeze(0).cpu().numpy()


def build_or_load_prototypes(force_rebuild: bool = False, device: str = "cpu"):
    """
    Builds or loads reference centroids:
    1. 'mosque': genuine verified mosque footprints
    2. 'confusor': false alarms (schools, malls, warehouses, villas)
    """
    global _PROTOTYPES
    if _PROTOTYPES is not None and not force_rebuild:
        return _PROTOTYPES

    if PROTOTYPES_PATH.exists() and not force_rebuild:
        try:
            _PROTOTYPES = torch.load(PROTOTYPES_PATH, map_location=device, weights_only=False)
            return _PROTOTYPES
        except Exception:
            pass

    print("[Stage 2] Building DINOv2 reference prototypes from verified dataset...")
    model = get_dino_model(device)

    # 1. Gather positive mosque crops from mosque_dataset_v2 val set
    val_img_dir = OUTPUT_DIR / "mosque_dataset_v2" / "val" / "images"
    val_lbl_dir = OUTPUT_DIR / "mosque_dataset_v2" / "val" / "labels"
    
    mosque_embeddings = []
    confusor_embeddings = []

    if val_img_dir.exists() and val_lbl_dir.exists():
        for img_path in sorted(val_img_dir.glob("*.jpg"))[:200]:
            lbl_path = val_lbl_dir / f"{img_path.stem}.txt"
            if not lbl_path.exists():
                continue
            txt = lbl_path.read_text().strip()
            try:
                img = Image.open(img_path).convert("RGB")
            except Exception:
                continue

            w_px, h_px = img.size
            if not txt:
                # Empty label file = Hard negative non-mosque tile (mall, school, desert, roundabout)
                crop = img.crop((w_px // 4, h_px // 4, 3 * w_px // 4, 3 * h_px // 4))
                emb = extract_embedding(crop, model, device)
                confusor_embeddings.append(emb)
            else:
                for line in txt.splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        xc, yc, bw, bh = map(float, parts[1:5])
                        x1 = int(max(0, (xc - bw / 2) * w_px))
                        y1 = int(max(0, (yc - bh / 2) * h_px))
                        x2 = int(min(w_px, (xc + bw / 2) * w_px))
                        y2 = int(min(h_px, (yc + bh / 2) * h_px))
                        if (x2 - x1) >= 20 and (y2 - y1) >= 20:
                            # Add slight 15% margin for context
                            margin_x = int((x2 - x1) * 0.15)
                            margin_y = int((y2 - y1) * 0.15)
                            cx1 = max(0, x1 - margin_x)
                            cy1 = max(0, y1 - margin_y)
                            cx2 = min(w_px, x2 + margin_x)
                            cy2 = min(h_px, y2 + margin_y)
                            crop = img.crop((cx1, cy1, cx2, cy2))
                            emb = extract_embedding(crop, model, device)
                            mosque_embeddings.append(emb)

    # 2. Add human-reviewed rejected false positives from active_learning_feedback.json
    feedback_file = OUTPUT_DIR / "active_learning_feedback.json"
    if feedback_file.exists():
        try:
            with open(feedback_file, "r", encoding="utf-8") as f:
                fb = json.load(f)
            for det_id, item in fb.items():
                if item.get("status") == "negative":
                    raw_file = item.get("raw_file")
                    if raw_file:
                        p = ROOT_DIR / raw_file
                        if p.exists():
                            try:
                                img = Image.open(p).convert("RGB")
                                w_px, h_px = img.size
                                box = item.get("box_yolo")
                                if box and len(box) >= 4:
                                    xc, yc, bw, bh = box[:4]
                                    x1 = int(max(0, (xc - bw / 2) * w_px))
                                    y1 = int(max(0, (yc - bh / 2) * h_px))
                                    x2 = int(min(w_px, (xc + bw / 2) * w_px))
                                    y2 = int(min(h_px, (yc + bh / 2) * h_px))
                                    crop = img.crop((x1, y1, x2, y2))
                                else:
                                    crop = img
                                emb = extract_embedding(crop, model, device)
                                confusor_embeddings.append(emb)
                            except Exception:
                                pass
        except Exception as e:
            print(f"[Stage 2] Note reading feedback: {e}")

    mosque_mat = np.array(mosque_embeddings) if mosque_embeddings else np.zeros((1, 384))
    conf_mat = np.array(confusor_embeddings) if confusor_embeddings else np.zeros((1, 384))

    mosque_centroid = np.mean(mosque_mat, axis=0)
    mosque_centroid /= (np.linalg.norm(mosque_centroid) + 1e-9)

    confusor_centroid = np.mean(conf_mat, axis=0)
    confusor_centroid /= (np.linalg.norm(confusor_centroid) + 1e-9)

    _PROTOTYPES = {
        "mosque_centroid": torch.tensor(mosque_centroid, dtype=torch.float32),
        "confusor_centroid": torch.tensor(confusor_centroid, dtype=torch.float32),
        "num_mosque_samples": len(mosque_embeddings),
        "num_confusor_samples": len(confusor_embeddings),
    }

    torch.save(_PROTOTYPES, PROTOTYPES_PATH)
    print(f"[Stage 2] Reference prototypes built: {len(mosque_embeddings)} mosques, {len(confusor_embeddings)} confusors.")
    return _PROTOTYPES


def verify_candidate_patch(
    crop_img: Image.Image,
    device: str = "cpu",
    threshold: float = 0.52,
) -> dict:
    """
    Verifies a candidate building crop against DINOv2 centroids.
    Returns:
        dict: {
            'is_mosque': bool,
            'verifier_score': float, # 0.0 to 1.0
            'mosque_sim': float,
            'confusor_sim': float,
            'reason': str
        }
    """
    model = get_dino_model(device)
    prototypes = build_or_load_prototypes(device=device)

    emb = extract_embedding(crop_img, model, device)
    emb_t = torch.tensor(emb, dtype=torch.float32)

    mosque_sim = float(torch.dot(emb_t, prototypes["mosque_centroid"]))
    confusor_sim = float(torch.dot(emb_t, prototypes["confusor_centroid"]))

    # Convert relative similarity to calibrated probability via temperature scaling
    temp = 0.15
    diff = (mosque_sim - confusor_sim) / temp
    prob_mosque = 1.0 / (1.0 + np.exp(-diff))

    is_verified = bool(prob_mosque >= threshold and (mosque_sim >= confusor_sim - 0.02))

    reason = "High visual agreement with Saudi mosque architecture" if is_verified else (
        f"Visual features closer to commercial/school/villa lookalikes (Mosque: {mosque_sim:.2f}, Confusor: {confusor_sim:.2f})"
    )

    return {
        "is_mosque": is_verified,
        "verifier_score": round(float(prob_mosque), 3),
        "mosque_sim": round(float(mosque_sim), 3),
        "confusor_sim": round(float(confusor_sim), 3),
        "reason": reason,
    }
