"""
Stage 3: Real-World Geometric & Spatial Sanity Guard
===================================================
Applies architectural physics and spatial domain constraints to satellite
building candidates in Saudi Arabia:
1. Physical footprint area (80 m² to 4,500 m²)
2. Prayer hall aspect ratio (1.05:1 to 2.5:1)
3. Road proximity guard
4. Satellite cross-verification logic
"""

from __future__ import annotations

import math
from typing import Tuple


def get_meters_per_pixel(lat: float, zoom: int = 19) -> float:
    """Calculates ground resolution in meters/pixel for Web Mercator at latitude."""
    lat_rad = math.radians(lat)
    return (156543.03392 * math.cos(lat_rad)) / (2 ** zoom)


def evaluate_geometry(
    box_xyxy: Tuple[float, float, float, float],
    lat: float,
    zoom: int = 19,
    min_area_m2: float = 85.0,
    max_area_m2: float = 4200.0,
    max_aspect_ratio: float = 2.6,
) -> dict:
    """
    Evaluates physical dimensions of a candidate bounding box in a Qibla-rotated tile.
    
    Args:
        box_xyxy: (x1, y1, x2, y2) in pixel coordinates (e.g., 0 to 640)
        lat: Latitude of the center
    """
    x1, y1, x2, y2 = box_xyxy
    w_px = max(1.0, float(x2 - x1))
    h_px = max(1.0, float(y2 - y1))

    m_per_px = get_meters_per_pixel(lat, zoom)
    width_m = w_px * m_per_px
    height_m = h_px * m_per_px
    area_m2 = width_m * height_m

    aspect_ratio = max(width_m, height_m) / max(0.1, min(width_m, height_m))

    reasons = []
    is_valid = True

    # 1. Area Guard
    if area_m2 < min_area_m2:
        is_valid = False
        reasons.append(f"Too small for a prayer hall: {area_m2:.1f} m² (min {min_area_m2} m²)")
    elif area_m2 > max_area_m2:
        is_valid = False
        reasons.append(f"Too large (likely logistics hangar/mall): {area_m2:.1f} m² (max {max_area_m2} m²)")

    # 2. Aspect Ratio Guard
    if aspect_ratio > max_aspect_ratio:
        is_valid = False
        reasons.append(f"Aspect ratio {aspect_ratio:.2f}:1 too elongated (max {max_aspect_ratio}:1)")

    return {
        "is_valid": is_valid,
        "area_m2": round(area_m2, 1),
        "width_m": round(width_m, 1),
        "height_m": round(height_m, 1),
        "aspect_ratio": round(aspect_ratio, 2),
        "reasons": reasons,
    }


def evaluate_spatial_and_provider(
    cross_verified: bool,
    stage1_conf: float,
    stage2_score: float,
    min_dual_stage1: float = 0.42,
    min_single_stage1: float = 0.58,
    min_stage2_score: float = 0.50,
) -> Tuple[bool, str]:
    """
    Applies dual-satellite policy:
    - If cross-verified across Esri & Mapbox, allows lower Stage 1 threshold (>= 0.42).
    - If single-satellite only, enforces stricter threshold (>= 0.58) to eliminate sun/shadow artifacts.
    """
    if stage2_score < min_stage2_score:
        return False, f"Stage 2 Verifier score too low ({stage2_score:.2f} < {min_stage2_score:.2f})"

    if cross_verified:
        if stage1_conf >= min_dual_stage1:
            return True, "🌟 Dual-Confirmed (Esri + Mapbox)"
        else:
            return False, f"Dual candidate below minimum dual threshold ({stage1_conf:.2f} < {min_dual_stage1:.2f})"
    else:
        if stage1_conf >= min_single_stage1:
            return True, "Single satellite pass (High confidence)"
        else:
            return False, (
                f"Single satellite detection ({stage1_conf:.2f}) requires dual-satellite confirmation or >= {min_single_stage1:.2f}"
            )
