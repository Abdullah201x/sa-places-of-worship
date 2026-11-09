"""
Step 1.1: Auto-Generating Mosque Bounding Boxes (Zero Manual Drawing!)
======================================================================
Implements Step 1.1 of the satellite detection plan:

1. From OSM (`places_of_worship_sa.geojson` + local `.osm.pbf`):
   - Filters for verified mosque polygon footprints (`geom_type == "Polygon"`, i.e. `osm_type == "way"`).
   - Extracts exact polygon rings `[(lon, lat), ...]` and geographic bounds
     `[min_lon, min_lat, max_lon, max_lat]` from the PBF extract via `osmium`.
   - Converts each polygon's bounds directly into Zoom-19 `512x512` patch pixel
     coordinates and normalized YOLO format `(x_center, y_center, width, height)`,
     plus Qibla-rotated YOLO bounding boxes ready for Step 1.2.

2. From KAUST/Wikidata (`suggested_mosques_sa.geojson` + `sa_regions.geojson` + `.osm.pbf`):
   - Assigns all 54,503 points to the 13 Saudi administrative regions (`SA-01`..`SA-12`, `SA-14`).
   - Matches point coordinates against untagged `building=*` footprints in the `.osm.pbf`
     extract using `osmium`, falling back to a Qibla-aligned architectural prior box
     in rural regions where OSM building footprints are not yet mapped.
   - Samples ~100 mosques per Saudi region (1,300 regional samples total) so the
     detector learns regional architecture across all 13 provinces.

3. Visual Verification Showcase:
   - Downloads Zoom-19 `512x512` satellite patches for a multi-region showcase
     (OSM polygons + KAUST/Wikidata PBF-matched footprints) and generates an
     interactive HTML report + annotated showcase images.
"""

from __future__ import annotations

import base64
import collections
import io
import json
import math
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import osmium
import numpy as np
import requests
from PIL import Image, ImageDraw
from shapely.geometry import Point, Polygon, shape
from shapely.prepared import prep

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "pipeline"))
from common import axis_deviation, calculate_qibla_azimuth, configure_utf8_output, find_pbf  # noqa: E402

configure_utf8_output()

OUTPUT_DIR = ROOT_DIR / "poc_satellite_output" / "step1_1_bboxes"
TILES_CACHE_DIR = ROOT_DIR / "poc_satellite_output" / "tile_cache"

ZOOM = 19
PATCH_SIZE = 512  # 512x512 pixels at Zoom 19 (~153m x 153m, ~0.30m/px)
MIN_MOSQUE_AREA_M2 = 45.0
MAX_MOSQUE_AREA_M2 = 10000.0
SAMPLES_PER_REGION = 100


# ---------------------------------------------------------------------------
# Web Mercator Zoom-19 Coordinate & Bounding Box Math
# ---------------------------------------------------------------------------


def latlon_to_global_px(lat: float, lon: float, zoom: int = ZOOM) -> tuple[float, float]:
    """Convert (lat, lon) to continuous global Web Mercator pixel coordinates at `zoom`."""
    lat_rad = math.radians(lat)
    n = 256.0 * (2.0**zoom)
    gx = (lon + 180.0) / 360.0 * n
    gy = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return gx, gy


def latlon_to_patch_px(
    lat: float,
    lon: float,
    center_lat: float,
    center_lon: float,
    zoom: int = ZOOM,
    patch_size: int = PATCH_SIZE,
) -> tuple[float, float]:
    """Convert (lat, lon) into pixel coordinates (px_x, px_y) on a `patch_size` patch centered at (center_lat, center_lon)."""
    cx_global, cy_global = latlon_to_global_px(center_lat, center_lon, zoom)
    gx, gy = latlon_to_global_px(lat, lon, zoom)
    half = patch_size / 2.0
    return half + (gx - cx_global), half + (gy - cy_global)


def rotate_point_ccw(
    px_x: float, px_y: float, angle_deg: float, cx: float = PATCH_SIZE / 2.0, cy: float = PATCH_SIZE / 2.0
) -> tuple[float, float]:
    """
    Rotate image pixel (px_x, px_y) counter-clockwise by `angle_deg` around (cx, cy),
    matching `PIL.Image.rotate(angle_deg)`.
    When `angle_deg = qibla_bearing`, the Qibla vector points straight UP (0 deg North).
    """
    rad = math.radians(angle_deg)
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)
    dx = px_x - cx
    dy = px_y - cy
    rx = cx + (dx * cos_a + dy * sin_a)
    ry = cy + (-dx * sin_a + dy * cos_a)
    return rx, ry


def compute_yolo_bboxes_from_ring(
    ring_lonlat: list[tuple[float, float]],
    center_lat: float,
    center_lon: float,
    qibla_bearing: float,
    zoom: int = ZOOM,
    patch_size: int = PATCH_SIZE,
) -> dict | None:
    """
    Given a polygon ring `[(lon, lat), ...]`, compute:
    1. Geographic bounding box `[min_lon, min_lat, max_lon, max_lat]`
    2. Unrotated Zoom-19 patch pixel box `[xmin_px, ymin_px, xmax_px, ymax_px]`
       and normalized YOLO `(x_center, y_center, width, height)`
    3. Qibla-rotated Zoom-19 patch pixel box and normalized YOLO
       `(x_center, y_center, width, height)` (for Step 1.2)
    """
    lons = [pt[0] for pt in ring_lonlat]
    lats = [pt[1] for pt in ring_lonlat]
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)

    # Convert polygon vertices to patch pixel coordinates
    patch_pts = [
        latlon_to_patch_px(lat, lon, center_lat, center_lon, zoom, patch_size)
        for lon, lat in ring_lonlat
    ]

    # 1. Unrotated bounding box (directly equivalent to converting [min_lon, min_lat, max_lon, max_lat])
    xs = [max(0.0, min(float(patch_size), p[0])) for p in patch_pts]
    ys = [max(0.0, min(float(patch_size), p[1])) for p in patch_pts]
    xmin_px, xmax_px = min(xs), max(xs)
    ymin_px, ymax_px = min(ys), max(ys)
    w_px = xmax_px - xmin_px
    h_px = ymax_px - ymin_px
    if w_px < 6.0 or h_px < 6.0:
        return None

    yolo_unrotated = [
        round(((xmin_px + xmax_px) / 2.0) / patch_size, 6),
        round(((ymin_px + ymax_px) / 2.0) / patch_size, 6),
        round(w_px / patch_size, 6),
        round(h_px / patch_size, 6),
    ]

    # 2. Qibla-rotated bounding box (vertices rotated by qibla_bearing so Qibla points UP)
    rot_pts = [rotate_point_ccw(px, py, qibla_bearing, patch_size / 2.0, patch_size / 2.0) for px, py in patch_pts]
    rxs = [max(0.0, min(float(patch_size), p[0])) for p in rot_pts]
    rys = [max(0.0, min(float(patch_size), p[1])) for p in rot_pts]
    r_xmin, r_xmax = min(rxs), max(rxs)
    r_ymin, r_ymax = min(rys), max(rys)
    rw_px = max(6.0, r_xmax - r_xmin)
    rh_px = max(6.0, r_ymax - r_ymin)

    yolo_qibla_rotated = [
        round(((r_xmin + r_xmax) / 2.0) / patch_size, 6),
        round(((r_ymin + r_ymax) / 2.0) / patch_size, 6),
        round(rw_px / patch_size, 6),
        round(rh_px / patch_size, 6),
    ]

    return {
        "geo_bbox": [round(min_lon, 6), round(min_lat, 6), round(max_lon, 6), round(max_lat, 6)],
        "pixel_bbox": [round(xmin_px, 1), round(ymin_px, 1), round(xmax_px, 1), round(ymax_px, 1)],
        "yolo_bbox": yolo_unrotated,
        "yolo_line": f"0 {yolo_unrotated[0]:.6f} {yolo_unrotated[1]:.6f} {yolo_unrotated[2]:.6f} {yolo_unrotated[3]:.6f}",
        "qibla_pixel_bbox": [round(r_xmin, 1), round(r_ymin, 1), round(r_xmax, 1), round(r_ymax, 1)],
        "qibla_yolo_bbox": yolo_qibla_rotated,
        "qibla_yolo_line": (
            f"0 {yolo_qibla_rotated[0]:.6f} {yolo_qibla_rotated[1]:.6f} "
            f"{yolo_qibla_rotated[2]:.6f} {yolo_qibla_rotated[3]:.6f}"
        ),
        "patch_polygon_px": [[round(px, 1), round(py, 1)] for px, py in patch_pts],
        "qibla_polygon_px": [[round(px, 1), round(py, 1)] for px, py in rot_pts],
    }


def make_qibla_oriented_box_ring(
    center_lat: float, center_lon: float, size_m: float, qibla_bearing: float
) -> list[tuple[float, float]]:
    """
    Construct a Qibla-aligned square building footprint ring `[(lon, lat), ...]` of side `size_m` meters
    centered at `(center_lat, center_lon)` for point-only rural mosques that lack an OSM building polygon.
    """
    m_per_deg_lat = 110_574.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(center_lat))
    half = size_m / 2.0
    theta = math.radians(qibla_bearing)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)

    # Local corners (east_m, north_m) rotated by Qibla bearing
    corners_local = [(-half, -half), (half, -half), (half, half), (-half, half)]
    ring = []
    for x_m, y_m in corners_local:
        east_m = x_m * cos_t + y_m * sin_t
        north_m = -x_m * sin_t + y_m * cos_t
        lon = center_lon + (east_m / m_per_deg_lon)
        lat = center_lat + (north_m / m_per_deg_lat)
        ring.append((round(lon, 6), round(lat, 6)))
    ring.append(ring[0])
    return ring


# ---------------------------------------------------------------------------
# Single-Pass OSM PBF Polygon Extractor & KAUST/Wikidata Building Matcher
# ---------------------------------------------------------------------------


class PbfFootprintMatcher(osmium.SimpleHandler):
    """
    In a single pass over the GCC `.osm.pbf`:
    1. Extracts exact polygon rings for all OSM `way` mosques from `places_of_worship_sa.geojson`.
    2. Matches KAUST/Wikidata candidate points (`suggested_mosques_sa.geojson`) to the nearest
       `building=*` polygon within 25 meters.
    """

    def __init__(self, osm_way_ids: set[int], sugg_grid: dict[tuple[int, int], list[tuple[int, float, float]]]):
        super().__init__()
        self.osm_way_ids = osm_way_ids
        self.sugg_grid = sugg_grid
        self.osm_polygons: dict[int, tuple[float, list[tuple[float, float]]]] = {}
        self.sugg_matches: dict[int, tuple[float, int, float, list[tuple[float, float]]]] = {}

    def way(self, w) -> None:
        wid = w.id
        is_osm_mosque = wid in self.osm_way_ids
        b_tag = w.tags.get("building", "")
        is_cand_building = b_tag in ("yes", "mosque")
        if not is_osm_mosque and not is_cand_building:
            return
        if len(w.nodes) < 4:
            return

        try:
            n0 = w.nodes[0]
            lon0, lat0 = n0.lon, n0.lat
        except osmium.InvalidLocationError:
            return

        cands = []
        if not is_osm_mosque:
            gx, gy = int(math.floor(lon0 / 0.002)), int(math.floor(lat0 / 0.002))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    cands.extend(self.sugg_grid.get((gx + dx, gy + dy), ()))
            if not cands:
                return

        try:
            coords = [(round(nd.lon, 6), round(nd.lat, 6)) for nd in w.nodes]
        except osmium.InvalidLocationError:
            return
        if coords[0] != coords[-1]:
            return

        m_lon = 111_320.0 * math.cos(math.radians(lat0))
        coords_m = [(x * m_lon, y * 110_574.0) for x, y in coords]
        poly_m = Polygon(coords_m)
        area_m2 = poly_m.area
        if area_m2 <= 0:
            return

        if is_osm_mosque:
            self.osm_polygons[wid] = (round(area_m2, 1), coords)
            if not is_cand_building or not cands:
                return

        if not (MIN_MOSQUE_AREA_M2 <= area_m2 <= MAX_MOSQUE_AREA_M2):
            return

        # Reject non-building canopies/plazas/spaghetti outlines via minimum rotated rectangle rectangularity
        if not poly_m.is_valid:
            poly_m = poly_m.buffer(0)
            if not poly_m.is_valid or poly_m.area <= 0:
                return
        mrr = poly_m.minimum_rotated_rectangle
        if mrr.area <= 0 or (poly_m.area / mrr.area) < 0.58:
            return

        # Compute principal wall orientation of the candidate building
        mrr_pts = list(mrr.exterior.coords)[:-1]
        qibla_deg = calculate_qibla_azimuth(lat0, lon0)
        qibla_dev = 45.0
        if len(mrr_pts) >= 4:
            for i in range(4):
                dx = mrr_pts[(i + 1) % 4][0] - mrr_pts[i][0]
                dy = mrr_pts[(i + 1) % 4][1] - mrr_pts[i][1]
                if math.hypot(dx, dy) > 0.5:
                    edge_az = math.degrees(math.atan2(dx, dy)) % 180.0
                    qibla_dev = min(qibla_dev, axis_deviation(edge_az, qibla_deg))

        # Untagged candidate buildings must reasonably align with Qibla (<= 22 deg) unless explicitly building=mosque
        if b_tag != "mosque" and qibla_dev > 22.0:
            return

        poly = Polygon(coords)
        if not poly.is_valid:
            poly = poly.buffer(0)
            if not poly.is_valid or poly.area <= 0 or poly.geom_type != "Polygon":
                return

        minx, miny, maxx, maxy = poly.bounds
        pad = 0.00024  # ~25m search tolerance (covers pins placed on minarets or courtyards)
        for s_idx, slon, slat in cands:
            if minx - pad <= slon <= maxx + pad and miny - pad <= slat <= maxy + pad:
                pt = Point(slon, slat)
                dist_deg = 0.0 if poly.covers(pt) else poly.exterior.distance(pt)
                dist_m = dist_deg * 111_000.0
                if dist_m <= 25.0:
                    prev = self.sugg_matches.get(s_idx)
                    if prev is None or dist_m < prev[0]:
                        self.sugg_matches[s_idx] = (round(dist_m, 1), wid, round(area_m2, 1), coords)


# ---------------------------------------------------------------------------
# Satellite Tile Fetching & Visual Annotation for Step 1.1 Report
# ---------------------------------------------------------------------------


MAPBOX_TOKEN = os.environ.get("MAPBOX_ACCESS_TOKEN", "")
if not MAPBOX_TOKEN:
    _env_file = ROOT_DIR / ".env"
    if _env_file.exists():
        for _line in _env_file.read_text(encoding="utf-8").splitlines():
            if _line.startswith("MAPBOX_ACCESS_TOKEN="):
                MAPBOX_TOKEN = _line.split("=", 1)[1].strip()



def _read_cached_tile(path: Path) -> Image.Image | None:
    """Open a cached tile; delete it and return None if it is empty, truncated or not an image."""
    if not path.exists():
        return None
    try:
        return Image.open(path).convert("RGB")
    except PermissionError:
        return None  # another thread is replacing it right now - a cache miss, not corruption
    except (OSError, ValueError):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None


def _write_atomic(path: Path, data: bytes | None = None, img: Image.Image | None = None) -> None:
    """Write via a temp file + rename, so an interrupted run never leaves a half-written tile.

    Best-effort: on Windows the rename fails if another thread is writing or reading the same tile
    at that moment. The tile is then simply not cached this time - never an error for the caller
    (an exception here used to make Mapbox fetches silently fall back to Esri).
    """
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        if img is not None:
            img.save(tmp, format="JPEG", quality=92)
        else:
            tmp.write_bytes(data)
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)

def _is_placeholder_tile(img: Image.Image) -> bool:
    """Detect Esri's gray 'Map data not yet available' tile (low std & near-zero color saturation)."""
    arr = np.asarray(img, dtype=np.float32)
    sat_mean = float((arr.max(axis=2) - arr.min(axis=2)).mean())
    return sat_mean < 1.5 and float(arr.std()) < 10.0


def _fetch_raw_esri_tile(z: int, x: int, y: int, session: requests.Session) -> Image.Image:
    TILES_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = TILES_CACHE_DIR / f"raw_{z}_{x}_{y}.jpg"
    img = _read_cached_tile(cache_path)
    if img is not None:
        if not _is_placeholder_tile(img):
            return img
        cache_path.unlink(missing_ok=True)

    url = f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
    headers = {"User-Agent": "SaudiMosqueMapStep1.1/1.0 (Academic/Hobbyist Research)"}
    resp = session.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    img = Image.open(io.BytesIO(resp.content)).convert("RGB")
    if not _is_placeholder_tile(img):
        _write_atomic(cache_path, data=resp.content)
    return img


def _fetch_raw_mapbox_tile(z: int, x: int, y: int, session: requests.Session) -> Image.Image:
    TILES_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = TILES_CACHE_DIR / f"raw_mapbox_{z}_{x}_{y}.jpg"
    img = _read_cached_tile(cache_path)
    if img is not None:
        if not _is_placeholder_tile(img):
            return img
        cache_path.unlink(missing_ok=True)

    url = f"https://api.mapbox.com/v4/mapbox.satellite/{z}/{x}/{y}.jpg?access_token={MAPBOX_TOKEN}"
    resp = session.get(url, timeout=15)
    resp.raise_for_status()
    img = Image.open(io.BytesIO(resp.content)).convert("RGB")
    if not _is_placeholder_tile(img):
        _write_atomic(cache_path, data=resp.content)
    return img


def fetch_single_tile(
    z: int, x: int, y: int, session: requests.Session, provider: str = "esri"
) -> Image.Image:
    """
    Fetch a 256x256 satellite tile at zoom `z` from either Esri or Mapbox, automatically
    falling back to upsampled Zoom `z-1` (18) or `z-2` (17) sub-tiles in rural areas.
    """
    TILES_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    prefix = f"{provider}_" if provider != "esri" else ""
    resolved_cache = TILES_CACHE_DIR / f"{prefix}{z}_{x}_{y}.jpg"
    cached_img = _read_cached_tile(resolved_cache)
    if cached_img is not None:
        if not _is_placeholder_tile(cached_img):
            return cached_img
        resolved_cache.unlink(missing_ok=True)

    fetch_raw = _fetch_raw_mapbox_tile if (provider == "mapbox" and MAPBOX_TOKEN) else _fetch_raw_esri_tile
    try:
        img = fetch_raw(z, x, y, session)
    except Exception:
        # Fallback to Esri if Mapbox throws an error
        img = _fetch_raw_esri_tile(z, x, y, session)

    if not _is_placeholder_tile(img):
        _write_atomic(resolved_cache, img=img)
        return img

    # Fallback to ancestor tiles (z-1 = Zoom 18, z-2 = Zoom 17) and crop exact sub-quadrant
    for d in (1, 2):
        anc_z = z - d
        scale = 1 << d
        try:
            anc_img = fetch_raw(anc_z, x >> d, y >> d, session)
        except Exception:
            anc_img = _fetch_raw_esri_tile(anc_z, x >> d, y >> d, session)
        if not _is_placeholder_tile(anc_img):
            sub_w = 256 // scale
            sx = (x % scale) * sub_w
            sy = (y % scale) * sub_w
            upsampled = anc_img.crop((sx, sy, sx + sub_w, sy + sub_w)).resize(
                (256, 256), Image.Resampling.LANCZOS
            )
            _write_atomic(resolved_cache, img=upsampled)
            return upsampled

    return img


def fetch_patch_512(lat: float, lon: float, zoom: int = ZOOM, size: int = PATCH_SIZE) -> Image.Image:
    """Fetch a 3x3 grid of 256x256 tiles around (lat, lon) and crop an exact centered `size x size` patch."""
    gx, gy = latlon_to_global_px(lat, lon, zoom)
    tx = int(math.floor(gx / 256.0))
    ty = int(math.floor(gy / 256.0))
    px = int(round(gx - tx * 256))
    py = int(round(gy - ty * 256))

    canvas = Image.new("RGB", (256 * 3, 256 * 3))
    with requests.Session() as session:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                tile_img = fetch_single_tile(zoom, tx + dx, ty + dy, session)
                canvas.paste(tile_img, ((dx + 1) * 256, (dy + 1) * 256))

    center_x = 256 + px
    center_y = 256 + py
    half = size // 2
    return canvas.crop((center_x - half, center_y - half, center_x + half, center_y + half))


def render_bbox_preview(raw_img: Image.Image, record: dict) -> tuple[Image.Image, Image.Image]:
    """
    Render:
    1. Unrotated Zoom-19 512x512 patch with exact polygon footprint (cyan) + YOLO bounding box (emerald green).
    2. Qibla-rotated Zoom-19 512x512 patch (Qibla pointing straight UP) with tight Qibla-aligned YOLO box.
    """
    # 1. Unrotated view
    unrot = raw_img.copy().convert("RGBA")
    ov1 = Image.new("RGBA", unrot.size, (0, 0, 0, 0))
    d1 = ImageDraw.Draw(ov1)

    poly_pts = [tuple(p) for p in record["bbox_data"]["patch_polygon_px"]]
    if len(poly_pts) >= 3:
        d1.polygon(poly_pts, fill=(6, 182, 212, 45), outline=(0, 229, 255, 230))
        d1.line(poly_pts, fill=(0, 229, 255, 240), width=2)

    x0, y0, x1, y1 = record["bbox_data"]["pixel_bbox"]
    d1.rectangle([x0, y0, x1, y1], outline=(16, 185, 129, 255), width=3)

    # Corner markers for YOLO box
    corner_len = 10
    for cx, cy, sx, sy in [(x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)]:
        d1.line([(cx, cy), (cx + sx * corner_len, cy)], fill=(52, 211, 153, 255), width=4)
        d1.line([(cx, cy), (cx, cy + sy * corner_len)], fill=(52, 211, 153, 255), width=4)

    # Qibla compass in top-right
    ccx, ccy, cr = unrot.width - 38, 38, 24
    d1.ellipse([(ccx - cr, ccy - cr), (ccx + cr, ccy + cr)], fill=(15, 23, 42, 200), outline=(255, 255, 255, 190))
    q_rad = math.radians(record["qibla_bearing"])
    qx = ccx + int(math.sin(q_rad) * (cr - 4))
    qy = ccy - int(math.cos(q_rad) * (cr - 4))
    d1.line([(ccx, ccy), (qx, qy)], fill=(250, 204, 21, 255), width=3)
    d1.ellipse([(qx - 3, qy - 3), (qx + 3, qy + 3)], fill=(250, 204, 21, 255))

    img_unrot = Image.alpha_composite(unrot, ov1).convert("RGB")

    # 2. Qibla-rotated view (Step 1.2 preview: Qibla pointing straight UP = 0 deg)
    rot_base = raw_img.rotate(record["qibla_bearing"], resample=Image.Resampling.BICUBIC, expand=False).convert("RGBA")
    ov2 = Image.new("RGBA", rot_base.size, (0, 0, 0, 0))
    d2 = ImageDraw.Draw(ov2)

    rpoly_pts = [tuple(p) for p in record["bbox_data"]["qibla_polygon_px"]]
    if len(rpoly_pts) >= 3:
        d2.polygon(rpoly_pts, fill=(6, 182, 212, 45), outline=(0, 229, 255, 230))
        d2.line(rpoly_pts, fill=(0, 229, 255, 240), width=2)

    rx0, ry0, rx1, ry1 = record["bbox_data"]["qibla_pixel_bbox"]
    d2.rectangle([rx0, ry0, rx1, ry1], outline=(250, 204, 21, 255), width=3)

    # Upward Qibla arrow in top-right
    d2.ellipse([(ccx - cr, ccy - cr), (ccx + cr, ccy + cr)], fill=(15, 23, 42, 200), outline=(255, 255, 255, 190))
    d2.line([(ccx, ccy + 10), (ccx, ccy - cr + 5)], fill=(250, 204, 21, 255), width=3)
    d2.ellipse([(ccx - 3, ccy - cr + 2), (ccx + 3, ccy - cr + 8)], fill=(250, 204, 21, 255))

    img_rot = Image.alpha_composite(rot_base, ov2).convert("RGB")
    return img_unrot, img_rot


def pil_to_base64(img: Image.Image, max_side: int = 384) -> str:
    if img.width > max_side:
        img = img.resize((max_side, max_side), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def main() -> None:
    t0 = time.time()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 78)
    print("STEP 1.1: AUTO-GENERATING MOSQUE BOUNDING BOXES (ZERO MANUAL DRAWING)")
    print("=" * 78)

    # 1. Load Saudi Regions
    regions_fc = json.loads((ROOT_DIR / "sa_regions.geojson").read_text(encoding="utf-8"))
    regions = []
    region_names = {}
    for feat in regions_fc["features"]:
        code = feat["properties"]["code"]
        name_en = feat["properties"]["name_en"]
        name_ar = feat["properties"]["name"]
        geom = shape(feat["geometry"])
        regions.append((code, name_en, name_ar, prep(geom), geom.bounds))
        region_names[code] = f"{name_en} ({name_ar})"
    regions.sort(key=lambda r: r[0])
    print(f"1. Loaded {len(regions)} Saudi administrative regions ({', '.join(r[0] for r in regions)}).")

    pbf_path = find_pbf()
    osm_jsonl_path = OUTPUT_DIR / "osm_way_bboxes.jsonl"
    kaust_jsonl_path = OUTPUT_DIR / "kaust_regional_1300_bboxes.jsonl"
    summary_path = OUTPUT_DIR / "step1_1_summary.json"
    reuse_jsonl = ("--reuse-jsonl" in sys.argv) and osm_jsonl_path.exists() and kaust_jsonl_path.exists() and summary_path.exists()

    if reuse_jsonl:
        print("2. Reusing cached Step 1.1 JSONL catalogs (--reuse-jsonl)...")
        osm_bbox_records = [json.loads(line) for line in osm_jsonl_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        kaust_regional_records = [json.loads(line) for line in kaust_jsonl_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        osm_by_region = collections.defaultdict(list)
        for rec in osm_bbox_records:
            osm_by_region[rec["region_code"]].append(rec)
        regional_stats = json.loads(summary_path.read_text(encoding="utf-8"))["regional_breakdown"]
    else:
        # 2. Load OSM `way` features from places_of_worship_sa.geojson
        places_fc = json.loads((ROOT_DIR / "places_of_worship_sa.geojson").read_text(encoding="utf-8"))
        osm_way_features = {}
        for feat in places_fc["features"]:
            props = feat["properties"]
            if props.get("geom_type") == "Polygon" and props.get("religion") == "muslim":
                if props.get("place_of_worship") == "musalla":
                    continue  # Skip open-air Eid musalla grounds
                osm_way_features[int(props["osm_id"])] = feat

        print(f"2. Found {len(osm_way_features):,} OSM muslim `way` polygon features in places_of_worship_sa.geojson.")

        # 3. Load KAUST/Wikidata points from suggested_mosques_sa.geojson & index in spatial grid
        sugg_fc = json.loads((ROOT_DIR / "suggested_mosques_sa.geojson").read_text(encoding="utf-8"))
        sugg_features = sugg_fc["features"]
        sugg_grid: dict[tuple[int, int], list[tuple[int, float, float]]] = collections.defaultdict(list)
        for idx, feat in enumerate(sugg_features):
            lon, lat = feat["geometry"]["coordinates"]
            gx, gy = int(math.floor(lon / 0.002)), int(math.floor(lat / 0.002))
            sugg_grid[(gx, gy)].append((idx, lon, lat))

        print(f"3. Indexed {len(sugg_features):,} KAUST/Wikidata points from suggested_mosques_sa.geojson.")

        # 4. Scan `.osm.pbf` once with Osmium to extract exact OSM way polygons + KAUST building matches
        print(f"4. Scanning PBF extract ({Path(pbf_path).name}) with Osmium for building footprints...")
        t_pbf = time.time()
        matcher = PbfFootprintMatcher(set(osm_way_features.keys()), sugg_grid)
        matcher.apply_file(pbf_path, locations=True)
        print(
            f"   PBF scan completed in {time.time() - t_pbf:.1f}s! "
            f"Extracted {len(matcher.osm_polygons):,} OSM mosque polygons & "
            f"matched {len(matcher.sugg_matches):,} KAUST/Wikidata points to OSM building footprints."
        )

        # 5. Convert OSM `way` polygons into Zoom-19 512x512 YOLO bounding boxes
        osm_bbox_records = []
        osm_by_region = collections.defaultdict(list)

        for wid, (area_m2, ring) in matcher.osm_polygons.items():
            if not (MIN_MOSQUE_AREA_M2 <= area_m2 <= MAX_MOSQUE_AREA_M2):
                continue
            feat = osm_way_features[wid]
            props = feat["properties"]
            lon, lat = feat["geometry"]["coordinates"]
            reg_code = props.get("region_code") or ""
            if not reg_code:
                pt = Point(lon, lat)
                for c, _, _, p_geom, (bx0, by0, bx1, by1) in regions:
                    if bx0 <= lon <= bx1 and by0 <= lat <= by1 and p_geom.contains(pt):
                        reg_code = c
                        break
            if not reg_code:
                continue

            qibla_deg = round(calculate_qibla_azimuth(lat, lon), 2)
            bbox_data = compute_yolo_bboxes_from_ring(ring, lat, lon, qibla_deg)
            if bbox_data is None:
                continue

            rec = {
                "id": f"osm_way_{wid}",
                "source": "osm_verified_way",
                "bbox_source": "osm_way_polygon",
                "osm_id": wid,
                "name": props.get("name") or "Mosque",
                "name_en": props.get("name_en") or "",
                "region_code": reg_code,
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "area_m2": area_m2,
                "qibla_bearing": qibla_deg,
                "bbox_data": bbox_data,
            }
            osm_bbox_records.append(rec)
            osm_by_region[reg_code].append(rec)

        print(
            f"5. Generated {len(osm_bbox_records):,} clean YOLO bounding boxes from OSM `way` polygons "
            f"(filtered to {MIN_MOSQUE_AREA_M2:.0f}–{MAX_MOSQUE_AREA_M2:,.0f} m²)."
        )

        # 6. Assign KAUST/Wikidata candidates to regions & sample 100 per Saudi region
        print(f"6. Assigning KAUST/Wikidata points to regions and sampling {SAMPLES_PER_REGION} per region...")
        sugg_by_region_matched: dict[str, list[tuple[int, dict]]] = collections.defaultdict(list)
        sugg_by_region_unmatched: dict[str, list[tuple[int, dict]]] = collections.defaultdict(list)

        for idx, feat in enumerate(sugg_features):
            props = feat["properties"]
            # Skip candidates that are too close (<150m) to an already-mapped OSM mosque
            nearest_osm = props.get("nearest_osm_m")
            if nearest_osm is not None and float(nearest_osm) < 150.0:
                continue
            lon, lat = feat["geometry"]["coordinates"]
            pt = Point(lon, lat)
            reg_code = ""
            for c, _, _, p_geom, (bx0, by0, bx1, by1) in regions:
                if bx0 <= lon <= bx1 and by0 <= lat <= by1 and p_geom.contains(pt):
                    reg_code = c
                    break
            if not reg_code:
                continue

            if idx in matcher.sugg_matches:
                sugg_by_region_matched[reg_code].append((idx, feat))
            elif not props.get("is_unnamed", False):
                sugg_by_region_unmatched[reg_code].append((idx, feat))

        rng = random.Random(42)
        kaust_regional_records = []
        regional_stats = []

        for code, name_en, name_ar, _, _ in regions:
            matched_list = sugg_by_region_matched[code]
            # Sort matched candidates by: named first, then closest pin-to-building distance
            matched_list.sort(
                key=lambda item: (
                    1 if item[1]["properties"].get("is_unnamed") else 0,
                    matcher.sugg_matches[item[0]][0],
                )
            )

            selected_records = []
            for idx, feat in matched_list[:SAMPLES_PER_REGION]:
                dist_m, b_wid, area_m2, ring = matcher.sugg_matches[idx]
                props = feat["properties"]
                # Center the patch on the matched building footprint centroid for clean centering
                poly = Polygon(ring)
                c_lon, c_lat = poly.centroid.x, poly.centroid.y
                qibla_deg = round(calculate_qibla_azimuth(c_lat, c_lon), 2)
                bbox_data = compute_yolo_bboxes_from_ring(ring, c_lat, c_lon, qibla_deg)
                if bbox_data is None:
                    continue
                selected_records.append(
                    {
                        "id": f"kaust_{props['qid']}",
                        "source": "kaust_wikidata_regional",
                        "bbox_source": "osm_pbf_building_match",
                        "qid": props["qid"],
                        "matched_osm_way_id": b_wid,
                        "pin_to_building_m": dist_m,
                        "name": props.get("name_ar") or props.get("name_en") or props["qid"],
                        "name_en": props.get("name_en") or "",
                        "region_code": code,
                        "lat": round(c_lat, 6),
                        "lon": round(c_lon, 6),
                        "area_m2": area_m2,
                        "qibla_bearing": qibla_deg,
                        "bbox_data": bbox_data,
                    }
                )

            pbf_matched_count = len(selected_records)
            needed = SAMPLES_PER_REGION - pbf_matched_count
            if needed > 0:
                pool = list(sugg_by_region_unmatched[code])
                rng.shuffle(pool)
                for _idx, feat in pool[:needed]:
                    props = feat["properties"]
                    lon, lat = feat["geometry"]["coordinates"]
                    name_str = props.get("name_ar") or props.get("name_en") or ""
                    is_grand = ("جامع" in name_str) or ("grand" in name_str.lower())
                    box_side_m = 30.0 if is_grand else 22.0
                    qibla_deg = round(calculate_qibla_azimuth(lat, lon), 2)
                    ring = make_qibla_oriented_box_ring(lat, lon, box_side_m, qibla_deg)
                    bbox_data = compute_yolo_bboxes_from_ring(ring, lat, lon, qibla_deg)
                    if bbox_data is None:
                        continue
                    selected_records.append(
                        {
                            "id": f"kaust_{props['qid']}",
                            "source": "kaust_wikidata_regional",
                            "bbox_source": "qibla_prior_box",
                            "qid": props["qid"],
                            "matched_osm_way_id": None,
                            "pin_to_building_m": None,
                            "name": name_str or props["qid"],
                            "name_en": props.get("name_en") or "",
                            "region_code": code,
                            "lat": round(lat, 6),
                            "lon": round(lon, 6),
                            "area_m2": round(box_side_m * box_side_m, 1),
                            "qibla_bearing": qibla_deg,
                            "bbox_data": bbox_data,
                        }
                    )

            kaust_regional_records.extend(selected_records)
            regional_stats.append(
                {
                    "region_code": code,
                    "name_en": name_en,
                    "name_ar": name_ar,
                    "osm_way_polygons": len(osm_by_region[code]),
                    "kaust_total_matched_in_pbf": len(matched_list),
                    "kaust_sampled_total": len(selected_records),
                    "kaust_sampled_pbf_footprints": pbf_matched_count,
                    "kaust_sampled_qibla_priors": len(selected_records) - pbf_matched_count,
                }
            )
            print(
                f"   [{code}] {name_en:<26} | OSM Way Boxes: {len(osm_by_region[code]):4d} | "
                f"KAUST Sampled: {len(selected_records):3d} "
                f"({pbf_matched_count} exact PBF footprints, {len(selected_records) - pbf_matched_count} Qibla priors)"
            )

        # 7. Save JSONL catalogs & summary JSON
        with open(osm_jsonl_path, "w", encoding="utf-8") as f:
            for rec in osm_bbox_records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        with open(kaust_jsonl_path, "w", encoding="utf-8") as f:
            for rec in kaust_regional_records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # 8. Download Zoom-19 512x512 Satellite Patches for a 16-Mosque Multi-Region Visual Showcase
    print("\n7. Downloading Zoom-19 (512x512) satellite patches for 16-mosque regional showcase...")
    showcase_items = []
    # Pick 8 diverse OSM `way` mosques across different regions + 8 KAUST PBF-matched mosques across regions
    showcase_regions_osm = ["SA-01", "SA-02", "SA-03", "SA-04", "SA-05", "SA-09", "SA-14", "SA-06"]
    for rcode in showcase_regions_osm:
        cands = [
            r for r in osm_by_region[rcode]
            if 250.0 <= r["area_m2"] <= 2800.0 and r["name"] != "Mosque"
        ] or osm_by_region[rcode]
        if cands:
            showcase_items.append(cands[0])

    showcase_regions_kaust = ["SA-01", "SA-02", "SA-03", "SA-04", "SA-05", "SA-07", "SA-09", "SA-14"]
    for rcode in showcase_regions_kaust:
        cands = [
            r for r in kaust_regional_records
            if r["region_code"] == rcode
            and r["bbox_source"] == "osm_pbf_building_match"
            and 220.0 <= r["area_m2"] <= 2800.0
        ]
        if cands:
            showcase_items.append(cands[0])

    showcase_dir = OUTPUT_DIR / "showcase"
    showcase_dir.mkdir(parents=True, exist_ok=True)

    def process_showcase(item: dict) -> dict:
        raw_img = fetch_patch_512(item["lat"], item["lon"], ZOOM, PATCH_SIZE)
        unrot_ann, rot_ann = render_bbox_preview(raw_img, item)
        return {
            **item,
            "raw_img": raw_img,
            "unrot_ann": unrot_ann,
            "rot_ann": rot_ann,
        }

    with ThreadPoolExecutor(max_workers=6) as pool:
        rendered_showcase = list(pool.map(process_showcase, showcase_items))

    for idx, item in enumerate(rendered_showcase):
        combined = Image.new("RGB", (PATCH_SIZE * 2 + 16, PATCH_SIZE), (15, 23, 42))
        combined.paste(item["unrot_ann"], (0, 0))
        combined.paste(item["rot_ann"], (PATCH_SIZE + 16, 0))
        out_file = showcase_dir / f"step1_1_{idx + 1:02d}_{item['region_code']}_{item['id']}.jpg"
        combined.save(out_file, quality=90)

    # 9. Save Summary Metadata & Interactive HTML Report
    total_kaust_pbf = sum(r["kaust_sampled_pbf_footprints"] for r in regional_stats)
    summary_payload = {
        "zoom": ZOOM,
        "patch_size_px": PATCH_SIZE,
        "total_osm_way_bboxes": len(osm_bbox_records),
        "total_kaust_regional_samples": len(kaust_regional_records),
        "kaust_pbf_footprint_matches": total_kaust_pbf,
        "kaust_qibla_prior_boxes": len(kaust_regional_records) - total_kaust_pbf,
        "total_combined_positive_bboxes": len(osm_bbox_records) + len(kaust_regional_records),
        "regional_breakdown": regional_stats,
    }
    summary_path = OUTPUT_DIR / "step1_1_summary.json"
    summary_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # Build HTML Report
    region_rows_html = []
    for st in regional_stats:
        region_rows_html.append(
            f"""
            <tr>
              <td><b>{st['region_code']}</b></td>
              <td>{st['name_en']} <span style="color:#94a3b8">({st['name_ar']})</span></td>
              <td style="text-align:right; font-weight:600; color:#38bdf8">{st['osm_way_polygons']:,}</td>
              <td style="text-align:right">{st['kaust_total_matched_in_pbf']:,}</td>
              <td style="text-align:right; font-weight:600; color:#10b981">{st['kaust_sampled_total']}</td>
              <td style="text-align:right">{st['kaust_sampled_pbf_footprints']} PBF / {st['kaust_sampled_qibla_priors']} Prior</td>
            </tr>
            """
        )

    cards_html = []
    for item in rendered_showcase:
        u_b64 = pil_to_base64(item["unrot_ann"])
        r_b64 = pil_to_base64(item["rot_ann"])
        src_badge = (
            '<span class="badge badge-osm">OSM Way Polygon</span>'
            if item["source"] == "osm_verified_way"
            else '<span class="badge badge-kaust">KAUST/Wikidata + PBF Building</span>'
        )
        cards_html.append(
            f"""
            <div class="card">
              <div class="card-header">
                <div>
                  <h3>{item['name']} <span class="sub">({item['region_code']})</span></h3>
                  <p class="meta-line">📍 {item['lat']:.5f}, {item['lon']:.5f} · Area: <b>{item['area_m2']:.0f} m²</b> · Qibla: <b>{item['qibla_bearing']}°</b></p>
                </div>
                {src_badge}
              </div>
              <div class="img-pair">
                <div>
                  <img src="{u_b64}" alt="Step 1.1 Unrotated BBox" />
                  <span class="caption">Step 1.1: Raw Zoom-19 (512×512) + <b style="color:#10b981">YOLO Box</b></span>
                </div>
                <div>
                  <img src="{r_b64}" alt="Step 1.2 Qibla-Rotated BBox" />
                  <span class="caption">Step 1.2 Ready: Qibla-Rotated (0° UP) + <b style="color:#facc15">Tight Box</b></span>
                </div>
              </div>
              <div class="code-box">
                <div><span class="lbl">Step 1.1 YOLO Label:</span> <code>{item['bbox_data']['yolo_line']}</code></div>
                <div><span class="lbl">Step 1.2 Qibla Label:</span> <code>{item['bbox_data']['qibla_yolo_line']}</code></div>
              </div>
            </div>
            """
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Step 1.1 — Auto-Generated Mosque YOLO Bounding Boxes</title>
  <style>
    body {{ font-family: system-ui, -apple-system, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 32px; }}
    .container {{ max-width: 1240px; margin: 0 auto; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; }}
    .subtitle {{ color: #94a3b8; margin-bottom: 24px; line-height: 1.5; }}
    .stats-bar {{ display: flex; gap: 16px; margin-bottom: 28px; flex-wrap: wrap; }}
    .stat-box {{ background: #1e293b; border: 1px solid #334155; padding: 16px 20px; border-radius: 12px; flex: 1; min-width: 200px; }}
    .stat-val {{ font-size: 26px; font-weight: 700; color: #38bdf8; }}
    .stat-label {{ font-size: 13px; color: #94a3b8; margin-top: 4px; }}
    table {{ width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 12px; overflow: hidden; margin-bottom: 32px; border: 1px solid #334155; }}
    th, td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid #334155; font-size: 14px; }}
    th {{ background: #0f172a; color: #cbd5e1; font-weight: 600; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(560px, 1fr)); gap: 20px; }}
    .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 14px; padding: 18px; }}
    .card-header {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 12px; }}
    .card-header h3 {{ margin: 0; font-size: 17px; }}
    .sub {{ color: #38bdf8; font-size: 14px; }}
    .meta-line {{ margin: 4px 0 0; font-size: 13px; color: #94a3b8; }}
    .badge {{ padding: 5px 10px; border-radius: 999px; font-size: 12px; font-weight: 700; white-space: nowrap; }}
    .badge-osm {{ background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.4); }}
    .badge-kaust {{ background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.4); }}
    .img-pair {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    .img-pair img {{ width: 100%; border-radius: 8px; border: 1px solid #475569; display: block; }}
    .caption {{ display: block; font-size: 12px; color: #cbd5e1; margin-top: 6px; text-align: center; }}
    .code-box {{ margin-top: 12px; background: #0f172a; padding: 10px 12px; border-radius: 8px; font-size: 12px; border: 1px solid #334155; display: flex; flex-direction: column; gap: 4px; }}
    .lbl {{ color: #94a3b8; display: inline-block; width: 145px; }}
    code {{ color: #a7f3d0; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>🛰️ Step 1.1 — Auto-Generated Mosque Bounding Boxes (Zero Manual Drawing)</h1>
    <p class="subtitle">
      Extracted directly from <code>places_of_worship_sa.geojson</code> + <code>suggested_mosques_sa.geojson</code> +
      <code>{Path(pbf_path).name}</code> at Zoom {ZOOM} (<code>{PATCH_SIZE}×{PATCH_SIZE}</code> px).
      Includes both standard North-up YOLO labels and Qibla-rotated YOLO labels for Step 1.2.
    </p>
    <div class="stats-bar">
      <div class="stat-box"><div class="stat-val">{len(osm_bbox_records):,}</div><div class="stat-label">OSM Verified Polygon Footprints</div></div>
      <div class="stat-box"><div class="stat-val">{len(kaust_regional_records):,}</div><div class="stat-label">KAUST Regional Samples (100 × 13 Regions)</div></div>
      <div class="stat-box"><div class="stat-val">{len(osm_bbox_records) + len(kaust_regional_records):,}</div><div class="stat-label">Total Auto-Boxed Mosques Ready for YOLO</div></div>
      <div class="stat-box"><div class="stat-val">0 hrs</div><div class="stat-label">Manual Bounding Box Drawing Time</div></div>
    </div>

    <h2>📊 Regional Architecture Coverage Across All 13 Saudi Provinces</h2>
    <table>
      <thead>
        <tr>
          <th>Code</th>
          <th>Region</th>
          <th style="text-align:right">OSM Way Polygons</th>
          <th style="text-align:right">KAUST Matched in PBF</th>
          <th style="text-align:right">KAUST Regional Sample</th>
          <th style="text-align:right">Sample Breakdown</th>
        </tr>
      </thead>
      <tbody>
        {''.join(region_rows_html)}
      </tbody>
    </table>

    <h2>🖼️ Multi-Region Zoom-19 (512×512) Auto-BBox Verification Showcase</h2>
    <div class="grid">
      {''.join(cards_html)}
    </div>
  </div>
</body>
</html>
"""
    report_path = OUTPUT_DIR / "step1_1_bbox_report.html"
    report_path.write_text(html, encoding="utf-8")

    print(f"\n8. Step 1.1 complete in {time.time() - t0:.1f}s!")
    print(f"   - OSM Way BBoxes JSONL:      {osm_jsonl_path}")
    print(f"   - KAUST Regional 1300 JSONL: {kaust_jsonl_path}")
    print(f"   - Summary JSON:              {summary_path}")
    print(f"   - Visual HTML Report:        {report_path}")


if __name__ == "__main__":
    main()
