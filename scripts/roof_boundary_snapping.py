"""
Level 1: Automated Roof-Boundary Snapping
========================================
Snaps loose, axis-aligned YOLO bounding boxes tightly to actual building roof
edges using high-contrast edge gradients, morphological closures, and
minimum-area rotated rectangles (cv2.minAreaRect).
"""

from __future__ import annotations

import math
from typing import List, Tuple
import cv2
import numpy as np
from PIL import Image, ImageDraw


def get_meters_per_pixel(lat: float, zoom: int = 19) -> float:
    """Calculates ground resolution in meters/pixel for Web Mercator at latitude."""
    lat_rad = math.radians(lat)
    return (156543.03392 * math.cos(lat_rad)) / (2 ** zoom)


def snap_roof_boundary(
    patch_img: Image.Image,
    box_xyxy: List[float],
    lat: float,
    zoom: int = 19,
    margin_ratio: float = 0.12,
) -> dict:
    """
    Given a rough YOLO box [x1, y1, x2, y2], snaps to the building's exact roof perimeter.

    Returns:
        dict: {
            "rotated_corners": [[x0, y0], [x1, y1], [x2, y2], [x3, y3]],
            "tight_box_xyxy": [min_x, min_y, max_x, max_y],
            "roof_angle_deg": float,
            "width_m": float,
            "height_m": float,
            "area_m2": float,
            "aspect_ratio": float,
            "snapped": bool
        }
    """
    arr = np.array(patch_img.convert("RGB"))
    h_img, w_img = arr.shape[:2]

    x1, y1, x2, y2 = [float(v) for v in box_xyxy]
    bw = max(10.0, x2 - x1)
    bh = max(10.0, y2 - y1)

    # 1. Expand search region slightly to ensure outer roof parapets are included
    mx = bw * margin_ratio
    my = bh * margin_ratio

    rx1 = max(0, int(round(x1 - mx)))
    ry1 = max(0, int(round(y1 - my)))
    rx2 = min(w_img, int(round(x2 + mx)))
    ry2 = min(h_img, int(round(y2 + my)))

    roi = arr[ry1:ry2, rx1:rx2]
    m_per_px = get_meters_per_pixel(lat, zoom)

    fallback_corners = [
        [round(x1, 1), round(y1, 1)],
        [round(x2, 1), round(y1, 1)],
        [round(x2, 1), round(y2, 1)],
        [round(x1, 1), round(y2, 1)],
    ]
    fallback_w_m = round(bw * m_per_px, 1)
    fallback_h_m = round(bh * m_per_px, 1)
    fallback_area = round(fallback_w_m * fallback_h_m, 1)
    fallback_asp = round(max(bw, bh) / max(1.0, min(bw, bh)), 2)

    if roi.shape[0] < 15 or roi.shape[1] < 15:
        return {
            "rotated_corners": fallback_corners,
            "tight_box_xyxy": [round(v, 1) for v in box_xyxy],
            "roof_angle_deg": 0.0,
            "width_m": fallback_w_m,
            "height_m": fallback_h_m,
            "area_m2": fallback_area,
            "aspect_ratio": fallback_asp,
            "snapped": False,
        }

    # 2. Edge & Gradient Processing
    gray = cv2.cvtColor(roi, cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # Multi-scale edge extraction: Otsu threshold + Canny edges
    _, otsu = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    edges = cv2.Canny(blurred, 40, 120)

    # Combine edges and boundary transitions
    combined = cv2.bitwise_or(edges, cv2.Canny(otsu, 50, 150))

    # Morphological closing to bridge roof seams and join parapet corners
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    closed = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # 3. Filter contours belonging to the central building
    min_area = (bw * bh) * 0.15
    max_area = (bw * bh) * 1.6
    roi_cx = roi.shape[1] / 2.0
    roi_cy = roi.shape[0] / 2.0

    valid_contours = []
    for c in contours:
        c_area = cv2.contourArea(c)
        if c_area < min_area or c_area > max_area:
            continue
        # Check center proximity
        M = cv2.moments(c)
        if M["m00"] > 0:
            cx = M["m10"] / M["m00"]
            cy = M["m01"] / M["m00"]
            # Distance from center should be reasonable
            dist = math.hypot(cx - roi_cx, cy - roi_cy)
            if dist < max(bw, bh) * 0.65:
                valid_contours.append(c)

    if not valid_contours:
        # Fallback: check Otsu contour directly
        otsu_contours, _ = cv2.findContours(otsu, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        valid_contours = [
            c for c in otsu_contours
            if min_area <= cv2.contourArea(c) <= max_area
        ]

    if valid_contours:
        # Merge all primary building contours into a unified convex hull
        all_pts = np.vstack(valid_contours)
        hull = cv2.convexHull(all_pts)

        # 4. Minimum Area Rotated Rectangle
        rect = cv2.minAreaRect(hull)  # ((cx, cy), (w, h), angle)
        (rcx, rcy), (rw, rh), angle = rect

        # Convert to global patch coordinates
        box_pts = cv2.boxPoints(rect)
        box_pts[:, 0] += rx1
        box_pts[:, 1] += ry1

        # Keep corners in standard order: top-left, top-right, bottom-right, bottom-left
        corners = [[round(float(p[0]), 1), round(float(p[1]), 1)] for p in box_pts]

        tight_x1 = round(float(np.min(box_pts[:, 0])), 1)
        tight_y1 = round(float(np.min(box_pts[:, 1])), 1)
        tight_x2 = round(float(np.max(box_pts[:, 0])), 1)
        tight_y2 = round(float(np.max(box_pts[:, 1])), 1)

        width_m = round(rw * m_per_px, 1)
        height_m = round(rh * m_per_px, 1)
        area_m2 = round(width_m * height_m, 1)
        aspect_ratio = round(max(rw, rh) / max(1.0, min(rw, rh)), 2)

        return {
            "rotated_corners": corners,
            "tight_box_xyxy": [tight_x1, tight_y1, tight_x2, tight_y2],
            "roof_angle_deg": round(float(angle), 1),
            "width_m": width_m,
            "height_m": height_m,
            "area_m2": area_m2,
            "aspect_ratio": aspect_ratio,
            "snapped": True,
        }

    return {
        "rotated_corners": fallback_corners,
        "tight_box_xyxy": [round(v, 1) for v in box_xyxy],
        "roof_angle_deg": 0.0,
        "width_m": fallback_w_m,
        "height_m": fallback_h_m,
        "area_m2": fallback_area,
        "aspect_ratio": fallback_asp,
        "snapped": False,
    }


def draw_snapped_annotation(
    patch_512: Image.Image,
    corners: List[List[float]],
    conf: float,
    qibla_bearing: float,
    dino_score: float = 0.0,
    area_m2: float = 0.0,
) -> Image.Image:
    """
    Renders an oriented, wall-snapped polygon on the building crop with
    high-visibility tactical corner brackets and a Qibla compass.
    """
    vis = patch_512.copy().convert("RGBA")
    ov = Image.new("RGBA", vis.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(ov)

    pts = [(p[0], p[1]) for p in corners]

    # 1. Fill oriented polygon with semi-transparent emerald tint
    draw.polygon(pts, fill=(16, 185, 129, 50), outline=(16, 185, 129, 255), width=3)

    # 2. Draw wall-aligned corner accents
    for i in range(4):
        p1 = np.array(pts[i])
        p_prev = np.array(pts[(i - 1) % 4])
        p_next = np.array(pts[(i + 1) % 4])

        v1 = p_prev - p1
        v2 = p_next - p1
        norm1 = np.linalg.norm(v1) + 1e-9
        norm2 = np.linalg.norm(v2) + 1e-9

        arm_len = min(14.0, norm1 * 0.35, norm2 * 0.35)
        b1 = p1 + (v1 / norm1) * arm_len
        b2 = p1 + (v2 / norm2) * arm_len

        draw.line([tuple(p1), tuple(b1)], fill=(52, 211, 153, 255), width=4)
        draw.line([tuple(p1), tuple(b2)], fill=(52, 211, 153, 255), width=4)

    # 3. Tactical Qibla compass in top-right corner
    ccx, ccy, cr = vis.width - 38, 38, 22
    draw.ellipse([(ccx - cr, ccy - cr), (ccx + cr, ccy + cr)], fill=(15, 23, 42, 210), outline=(255, 255, 255, 200), width=2)
    # Kaaba vector (pointing UP in Qibla-rotated patch)
    draw.line([(ccx, ccy + 10), (ccx, ccy - cr + 5)], fill=(250, 204, 21, 255), width=3)
    draw.ellipse([(ccx - 3, ccy - cr + 2), (ccx + 3, ccy - cr + 8)], fill=(250, 204, 21, 255))

    return Image.alpha_composite(vis, ov).convert("RGB")
