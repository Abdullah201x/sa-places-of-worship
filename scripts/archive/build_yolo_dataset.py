"""
Phase 1 (Steps 1.2 & 1.3) + Step 2.1: Complete Qibla-Normalized YOLO Dataset Builder
====================================================================================
Implements Steps 1.2, 1.3, and 2.1 of the satellite detection plan:

1. Step 1.2 — Borderless Qibla-Rotation Normalization:
   - Fetches a larger `740x740` Zoom-19 satellite window around each target coordinate,
     rotates by `qibla_bearing` so the Qibla direction always points straight UP (0° North),
     and center-crops the inner `512x512` patch — eliminating black corner triangles while
     making all mosque prayer-hall walls strictly horizontal & vertical.
   - Uses exact Qibla-rotated polygon bounding boxes from Step 1.1 (`qibla_yolo_bbox`) and
     automatically includes secondary YOLO boxes if multiple mapped mosques appear in one patch.

2. Step 1.3 — Mining 600 Real Saudi "Hard Negatives" (30% of Dataset):
   - Scans the local `.osm.pbf` extract + `sa_regions.geojson` to sample 600 non-mosque tiles
     strictly >= 250m away from all 68,525 OSM & KAUST mosques:
       * 150 Roundabouts (`junction=roundabout` — circular dome lookalikes)
       * 150 Schools & Universities (`amenity=school/university/college` — courtyard lookalikes)
       * 150 Malls, Palaces/Halls, Commercial Roofs & Hospitals (large roofs + parking lots)
       *  75 Highway Interchanges (`highway=motorway_junction` / `trunk_link`)
       *  75 Desert Sand Dunes, Farms & Rural Terrain across all 13 Saudi regions
   - Applies the exact same borderless Qibla-rotation (`740x740 -> rotate -> 512x512`) to
     every hard negative so positives and negatives share identical pixel resampling statistics,
     with empty `.txt` YOLO label files.

3. Step 2.1 — Standard YOLOv11 Folder Structure & Zip Export:
   - Exports `2,000` patches (`1,400` stratified regional positives + `600` hard negatives) into
     `mosque_dataset/` (`1,600` train / `400` val), writes portable `data.yaml`, packages
     `mosque_dataset.zip` ready for Kaggle / Google Colab T4 GPUs, and builds a visual HTML report.
"""

from __future__ import annotations

import base64
import collections
import io
import json
import math
import random
import shutil
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import osmium
import requests
from PIL import Image, ImageDraw
from requests.adapters import HTTPAdapter
from shapely.geometry import Point, shape
from shapely.prepared import prep
from urllib3.util.retry import Retry

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "pipeline"))
sys.path.insert(0, str(ROOT_DIR / "scripts"))

from common import calculate_qibla_azimuth, configure_utf8_output, find_pbf  # noqa: E402
from step1_1_generate_bboxes import (  # noqa: E402
    PATCH_SIZE,
    TILES_CACHE_DIR,
    ZOOM,
    _is_placeholder_tile,
    compute_yolo_bboxes_from_ring,
    fetch_single_tile,
    latlon_to_global_px,
)

configure_utf8_output()

STEP1_1_DIR = ROOT_DIR / "poc_satellite_output" / "step1_1_bboxes"
DATASET_DIR = ROOT_DIR / "poc_satellite_output" / "mosque_dataset"
DATASET_ZIP_PATH = ROOT_DIR / "poc_satellite_output" / "mosque_dataset.zip"
REPORT_PATH = ROOT_DIR / "poc_satellite_output" / "step1_2_3_dataset_report.html"
HARD_NEG_CACHE = STEP1_1_DIR / "hard_negatives_600.jsonl"

OUTER_HALF = 370  # 740x740 pre-rotation crop (> 256 * sqrt(2) = 362.04 px) -> zero black corners!
TARGET_POSITIVES = 1400
TARGET_HARD_NEGATIVES = 600  # 30.0% of 2,000 total patches
VAL_FRACTION = 0.20          # 1,600 train + 400 val = 2,000 total


# ---------------------------------------------------------------------------
# Fast Spatial Distance Guard Against All 68,525 Known & Suggested Mosques
# ---------------------------------------------------------------------------


class MosqueProximityIndex:
    """Grid index over all OSM + KAUST mosques to guarantee hard negatives contain zero mosques."""

    def __init__(self, cell_deg: float = 0.003):
        self.cell_deg = cell_deg
        self.grid: dict[tuple[int, int], list[tuple[float, float]]] = collections.defaultdict(list)

    def add(self, lat: float, lon: float) -> None:
        gx = int(math.floor(lon / self.cell_deg))
        gy = int(math.floor(lat / self.cell_deg))
        self.grid[(gx, gy)].append((lat, lon))

    def has_mosque_within_m(self, lat: float, lon: float, min_dist_m: float = 250.0) -> bool:
        gx = int(math.floor(lon / self.cell_deg))
        gy = int(math.floor(lat / self.cell_deg))
        m_lat = 110_574.0
        m_lon = 111_320.0 * math.cos(math.radians(lat))
        r2 = min_dist_m * min_dist_m
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for mlat, mlon in self.grid.get((gx + dx, gy + dy), ()):
                    d_y = (lat - mlat) * m_lat
                    d_x = (lon - mlon) * m_lon
                    if d_x * d_x + d_y * d_y <= r2:
                        return True
        return False


def build_all_mosques_index() -> tuple[MosqueProximityIndex, dict[tuple[int, int], list[dict]]]:
    """
    Build:
    1. `MosqueProximityIndex` of all 14,022 OSM + 54,503 KAUST mosques (68,525 points).
    2. Spatial lookup of polygon-boxed mosques from Step 1.1 so multi-mosque patches get all boxes.
    """
    prox = MosqueProximityIndex(cell_deg=0.003)

    places_fc = json.loads((ROOT_DIR / "places_of_worship_sa.geojson").read_text(encoding="utf-8"))
    for feat in places_fc["features"]:
        lon, lat = feat["geometry"]["coordinates"]
        prox.add(lat, lon)

    sugg_fc = json.loads((ROOT_DIR / "suggested_mosques_sa.geojson").read_text(encoding="utf-8"))
    for feat in sugg_fc["features"]:
        lon, lat = feat["geometry"]["coordinates"]
        prox.add(lat, lon)

    poly_grid: dict[tuple[int, int], list[dict]] = collections.defaultdict(list)
    for path in (STEP1_1_DIR / "osm_way_bboxes.jsonl", STEP1_1_DIR / "kaust_regional_1300_bboxes.jsonl"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            gx = int(math.floor(rec["lon"] / 0.002))
            gy = int(math.floor(rec["lat"] / 0.002))
            poly_grid[(gx, gy)].append(rec)

    return prox, poly_grid


# ---------------------------------------------------------------------------
# Step 1.3: Mining Hard Negatives from `.osm.pbf` + Saudi Desert/Rural Terrain
# ---------------------------------------------------------------------------


class HardNegativeMiner(osmium.SimpleHandler):
    """Extracts candidate coordinates for roundabouts, schools/universities, malls/halls, and interchanges."""

    def __init__(self, sa_bounds: tuple[float, float, float, float]):
        super().__init__()
        self.minx, self.miny, self.maxx, self.maxy = sa_bounds
        self.roundabouts: list[tuple[float, float, str]] = []
        self.schools: list[tuple[float, float, str]] = []
        self.large_roofs: list[tuple[float, float, str]] = []
        self.interchanges: list[tuple[float, float, str]] = []

    def _in_bbox(self, lon: float, lat: float) -> bool:
        return self.minx <= lon <= self.maxx and self.miny <= lat <= self.maxy

    def node(self, n) -> None:
        tags = n.tags
        if not tags:
            return
        hw = tags.get("highway", "")
        am = tags.get("amenity", "")
        sh = tags.get("shop", "")
        if hw != "motorway_junction" and am not in ("school", "university", "college", "hospital", "events_venue") and sh != "mall":
            return
        try:
            lon, lat = round(n.location.lon, 6), round(n.location.lat, 6)
        except osmium.InvalidLocationError:
            return
        if not self._in_bbox(lon, lat):
            return

        name = tags.get("name") or tags.get("name:en") or ""
        if hw == "motorway_junction":
            self.interchanges.append((lat, lon, name or "Highway Interchange"))
        elif am in ("school", "university", "college"):
            self.schools.append((lat, lon, name or am.title()))
        else:
            self.large_roofs.append((lat, lon, name or (sh or am).title()))

    def way(self, w) -> None:
        tags = w.tags
        if not tags or len(w.nodes) < 3:
            return
        junc = tags.get("junction", "")
        am = tags.get("amenity", "")
        sh = tags.get("shop", "")
        bldg = tags.get("building", "")
        hw = tags.get("highway", "")

        cat = ""
        if junc == "roundabout":
            cat = "roundabout"
        elif am in ("school", "university", "college") or bldg in ("school", "university", "college"):
            cat = "school"
        elif (
            sh in ("mall", "department_store", "supermarket")
            or bldg in ("mall", "commercial", "retail", "hospital", "stadium", "civic", "public", "warehouse")
            or am in ("hospital", "events_venue", "conference_centre", "marketplace", "community_centre")
        ):
            cat = "large_roof"
        elif hw in ("motorway_link", "trunk_link") and len(w.nodes) >= 6:
            cat = "interchange"
        else:
            return

        # Make sure this building/site isn't tagged as a mosque
        if am in ("place_of_worship", "mosque") or bldg == "mosque" or tags.get("religion") == "muslim":
            return

        try:
            n0 = w.nodes[0]
            if not self._in_bbox(n0.lon, n0.lat):
                return
            lons = [nd.lon for nd in w.nodes]
            lats = [nd.lat for nd in w.nodes]
        except osmium.InvalidLocationError:
            return

        lat = round(sum(lats) / len(lats), 6)
        lon = round(sum(lons) / len(lons), 6)
        name = tags.get("name") or tags.get("name:en") or ""

        if cat == "roundabout":
            self.roundabouts.append((lat, lon, name or "Urban Roundabout"))
        elif cat == "school":
            self.schools.append((lat, lon, name or "School / Campus Courtyard"))
        elif cat == "large_roof":
            self.large_roofs.append((lat, lon, name or f"Large {(sh or bldg or am).title()} Roof"))
        elif cat == "interchange":
            self.interchanges.append((lat, lon, name or "Highway Interchange"))


def load_or_mine_hard_negatives(
    regions: list[tuple[str, str, str, object, tuple[float, float, float, float]]],
    sa_prep: object,
    sa_bounds: tuple[float, float, float, float],
    prox_index: MosqueProximityIndex,
) -> list[dict]:
    """Load cached 600 hard negatives or mine them fresh from `.osm.pbf` + Saudi desert terrain."""
    if HARD_NEG_CACHE.exists():
        cached = [json.loads(l) for l in HARD_NEG_CACHE.read_text(encoding="utf-8").splitlines() if l.strip()]
        if len(cached) == TARGET_HARD_NEGATIVES:
            print(f"   Loaded {len(cached)} cached Saudi hard-negative locations from {HARD_NEG_CACHE.name}.")
            return cached

    pbf_path = find_pbf()
    print(f"   Mining hard negatives (roundabouts, schools, malls, interchanges) from {Path(pbf_path).name}...")
    t0 = time.time()
    miner = HardNegativeMiner(sa_bounds)
    miner.apply_file(pbf_path, locations=True)
    print(
        f"   PBF scan found {len(miner.roundabouts):,} roundabouts, {len(miner.schools):,} schools/campuses, "
        f"{len(miner.large_roofs):,} large roofs/malls, {len(miner.interchanges):,} interchanges in {time.time() - t0:.1f}s."
    )

    rng = random.Random(2026)

    def assign_region(lat: float, lon: float) -> str:
        pt = Point(lon, lat)
        for code, _, _, p_geom, (bx0, by0, bx1, by1) in regions:
            if bx0 <= lon <= bx1 and by0 <= lat <= by1 and p_geom.contains(pt):
                return code
        return ""

    def filter_and_sample(
        raw_cands: list[tuple[float, float, str]], quota: int, category: str
    ) -> list[dict]:
        pool = list(raw_cands)
        rng.shuffle(pool)
        chosen: list[dict] = []
        used_cells: set[tuple[int, int]] = set()  # Keep hard negatives >= ~330m apart from each other

        for lat, lon, title in pool:
            cell = (int(math.floor(lon / 0.003)), int(math.floor(lat / 0.003)))
            if cell in used_cells:
                continue
            if prox_index.has_mosque_within_m(lat, lon, min_dist_m=260.0):
                continue
            reg_code = assign_region(lat, lon)
            if not reg_code:
                continue
            used_cells.add(cell)
            qibla_deg = round(calculate_qibla_azimuth(lat, lon), 2)
            chosen.append(
                {
                    "id": f"neg_{category}_{len(chosen) + 1:03d}",
                    "source": "hard_negative",
                    "category": category,
                    "name": title,
                    "region_code": reg_code,
                    "lat": lat,
                    "lon": lon,
                    "qibla_bearing": qibla_deg,
                    "yolo_lines": [],
                }
            )
            if len(chosen) >= quota:
                break
        return chosen

    neg_roundabouts = filter_and_sample(miner.roundabouts, 150, "roundabout")
    neg_schools = filter_and_sample(miner.schools, 150, "school_courtyard")
    neg_roofs = filter_and_sample(miner.large_roofs, 150, "mall_large_roof")
    neg_interchanges = filter_and_sample(miner.interchanges, 75, "highway_interchange")

    # Fill remaining quota (~75) with desert sand dunes, farms & open terrain across all 13 regions
    desert_quota = TARGET_HARD_NEGATIVES - (
        len(neg_roundabouts) + len(neg_schools) + len(neg_roofs) + len(neg_interchanges)
    )
    neg_desert: list[dict] = []
    per_reg_target = max(1, math.ceil(desert_quota / len(regions)))
    for code, name_en, _, p_geom, (bx0, by0, bx1, by1) in regions:
        reg_got = 0
        attempts = 0
        while reg_got < per_reg_target and len(neg_desert) < desert_quota and attempts < 400:
            attempts += 1
            lon = round(rng.uniform(bx0, bx1), 6)
            lat = round(rng.uniform(by0, by1), 6)
            pt = Point(lon, lat)
            if not p_geom.contains(pt):
                continue
            if prox_index.has_mosque_within_m(lat, lon, min_dist_m=500.0):
                continue
            qibla_deg = round(calculate_qibla_azimuth(lat, lon), 2)
            neg_desert.append(
                {
                    "id": f"neg_desert_terrain_{len(neg_desert) + 1:03d}",
                    "source": "hard_negative",
                    "category": "desert_terrain",
                    "name": f"Desert / Unbuilt Terrain ({name_en})",
                    "region_code": code,
                    "lat": lat,
                    "lon": lon,
                    "qibla_bearing": qibla_deg,
                    "yolo_lines": [],
                }
            )
            reg_got += 1

    all_negatives = neg_roundabouts + neg_schools + neg_roofs + neg_interchanges + neg_desert
    with open(HARD_NEG_CACHE, "w", encoding="utf-8") as f:
        for rec in all_negatives:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(
        f"   Sampled {len(all_negatives)} verified mosque-free Hard Negatives: "
        f"{len(neg_roundabouts)} roundabouts, {len(neg_schools)} schools, "
        f"{len(neg_roofs)} malls/large roofs, {len(neg_interchanges)} interchanges, "
        f"{len(neg_desert)} desert/terrain."
    )
    return all_negatives


# ---------------------------------------------------------------------------
# Stratified Selection of 1,400 Positive Mosques Across All 13 Regions
# ---------------------------------------------------------------------------


def select_1400_positives(
    poly_grid: dict[tuple[int, int], list[dict]],
) -> list[dict]:
    """
    Select 1,400 high-precision positive mosques stratified across all 13 Saudi regions,
    prioritizing exact OSM way & KAUST PBF building footprints, and attaching secondary
    YOLO bounding boxes if a neighbor polygon mosque falls inside the same 512x512 patch.
    """
    osm_recs = [
        json.loads(l)
        for l in (STEP1_1_DIR / "osm_way_bboxes.jsonl").read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    kaust_recs = [
        json.loads(l)
        for l in (STEP1_1_DIR / "kaust_regional_1300_bboxes.jsonl").read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]

    # Combine exact polygon footprints first, deduplicating any building shared between OSM & KAUST
    by_region_exact: dict[str, list[dict]] = collections.defaultdict(list)
    by_region_prior: dict[str, list[dict]] = collections.defaultdict(list)
    seen_grid_15m: set[tuple[int, int]] = set()

    for rec in kaust_recs + osm_recs:
        key15 = (int(round(rec["lon"] / 0.00015)), int(round(rec["lat"] / 0.00015)))
        if key15 in seen_grid_15m:
            continue
        seen_grid_15m.add(key15)
        if rec["bbox_source"] in ("osm_way_polygon", "osm_pbf_building_match"):
            by_region_exact[rec["region_code"]].append(rec)
        else:
            by_region_prior[rec["region_code"]].append(rec)

    rng = random.Random(42)
    for code in by_region_exact:
        rng.shuffle(by_region_exact[code])
    for code in by_region_prior:
        rng.shuffle(by_region_prior[code])

    # Regional quotas summing to 1,400 across all 13 Saudi provinces
    # Small provinces get all their exact footprints (+ small top-up for SA-11), major provinces fill the rest
    quotas = {
        "SA-01": 270,  # Riyadh
        "SA-02": 250,  # Makkah / Jeddah / Taif
        "SA-03": 150,  # Madinah
        "SA-04": 160,  # Eastern Province
        "SA-05": 150,  # Al-Qassim
        "SA-06": 60,   # Ha'il
        "SA-07": 90,   # Tabuk
        "SA-08": 22,   # Northern Borders
        "SA-09": 100,  # Jazan
        "SA-10": 24,   # Najran
        "SA-11": 20,   # Al-Bahah
        "SA-12": 44,   # Al Jawf
        "SA-14": 60,   # 'Asir
    }
    assert sum(quotas.values()) == TARGET_POSITIVES

    selected: list[dict] = []
    for code, q in sorted(quotas.items()):
        picks = by_region_exact[code][:q]
        if len(picks) < q:
            picks = picks + by_region_prior[code][: (q - len(picks))]
        selected.extend(picks)

    # Check if any second mapped polygon mosque falls inside each positive's rotated 512x512 patch
    enriched: list[dict] = []
    for rec in selected:
        yolo_lines = [rec["bbox_data"]["qibla_yolo_line"]]
        gx = int(math.floor(rec["lon"] / 0.002))
        gy = int(math.floor(rec["lat"] / 0.002))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other in poly_grid.get((gx + dx, gy + dy), ()):
                    if other["id"] == rec["id"]:
                        continue
                    dist_deg = math.hypot(other["lon"] - rec["lon"], other["lat"] - rec["lat"])
                    if dist_deg < 0.00015 or dist_deg > 0.00085:
                        continue
                    # Reproject neighbor's polygon vertices into this patch's center & Qibla frame
                    # Approximate geographic ring from unrotated patch_polygon_px or geo_bbox
                    min_lon, min_lat, max_lon, max_lat = other["bbox_data"]["geo_bbox"]
                    ring_approx = [
                        (min_lon, min_lat),
                        (max_lon, min_lat),
                        (max_lon, max_lat),
                        (min_lon, max_lat),
                        (min_lon, min_lat),
                    ]
                    other_box = compute_yolo_bboxes_from_ring(
                        ring_approx, rec["lat"], rec["lon"], rec["qibla_bearing"], ZOOM, PATCH_SIZE
                    )
                    if other_box is not None:
                        xc, yc, bw, bh = other_box["qibla_yolo_bbox"]
                        if 0.03 < xc < 0.97 and 0.03 < yc < 0.97 and bw >= 0.025 and bh >= 0.025:
                            yolo_lines.append(other_box["qibla_yolo_line"])

        enriched.append(
            {
                "id": rec["id"],
                "source": rec["source"],
                "category": rec["bbox_source"],
                "name": rec["name"],
                "region_code": rec["region_code"],
                "lat": rec["lat"],
                "lon": rec["lon"],
                "qibla_bearing": rec["qibla_bearing"],
                "yolo_lines": yolo_lines,
            }
        )

    return enriched


# ---------------------------------------------------------------------------
# Step 1.2: Borderless Qibla-Rotated 512x512 Patch Fetcher
# ---------------------------------------------------------------------------


def make_http_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.4,
        status_forcelist=(429, 500, 502, 503, 504),
    )
    adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def fetch_borderless_qibla_patch(
    lat: float,
    lon: float,
    qibla_bearing: float,
    session: requests.Session,
    zoom: int = ZOOM,
    patch_size: int = PATCH_SIZE,
) -> Image.Image:
    """
    1. Crop an exact `740x740` Web Mercator window around `(lat, lon)` at Zoom 19.
    2. Rotate counter-clockwise by `qibla_bearing` so Qibla points straight UP (0° North).
    3. Center-crop the inner `512x512` patch — completely free of black corner triangles!
    """
    gx, gy = latlon_to_global_px(lat, lon, zoom)
    ix = int(round(gx))
    iy = int(round(gy))

    tx0 = (ix - OUTER_HALF) // 256
    tx1 = (ix + OUTER_HALF - 1) // 256
    ty0 = (iy - OUTER_HALF) // 256
    ty1 = (iy + OUTER_HALF - 1) // 256

    canvas_w = (tx1 - tx0 + 1) * 256
    canvas_h = (ty1 - ty0 + 1) * 256
    canvas = Image.new("RGB", (canvas_w, canvas_h))

    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            tile_img = fetch_single_tile(zoom, tx, ty, session)
            canvas.paste(tile_img, ((tx - tx0) * 256, (ty - ty0) * 256))

    x_off = (ix - OUTER_HALF) - tx0 * 256
    y_off = (iy - OUTER_HALF) - ty0 * 256
    outer_size = OUTER_HALF * 2
    crop_740 = canvas.crop((x_off, y_off, x_off + outer_size, y_off + outer_size))

    rot_740 = crop_740.rotate(qibla_bearing, resample=Image.Resampling.BICUBIC, expand=False)
    margin = OUTER_HALF - (patch_size // 2)
    return rot_740.crop((margin, margin, margin + patch_size, margin + patch_size))


# ---------------------------------------------------------------------------
# Visual Verification Report Renderer
# ---------------------------------------------------------------------------


def annotate_yolo_patch(img: Image.Image, yolo_lines: list[str], is_positive: bool) -> Image.Image:
    vis = img.copy().convert("RGBA")
    ov = Image.new("RGBA", vis.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(ov)
    w, h = vis.size

    for line in yolo_lines:
        parts = line.split()
        _, xc, yc, bw, bh = [float(v) for v in parts]
        x0 = (xc - bw / 2.0) * w
        y0 = (yc - bh / 2.0) * h
        x1 = (xc + bw / 2.0) * w
        y1 = (yc + bh / 2.0) * h
        draw.rectangle([x0, y0, x1, y1], fill=(16, 185, 129, 32), outline=(16, 185, 129, 255), width=3)

    # Upward Qibla badge in top-right corner
    ccx, ccy, cr = w - 36, 36, 22
    draw.ellipse([(ccx - cr, ccy - cr), (ccx + cr, ccy + cr)], fill=(15, 23, 42, 200), outline=(255, 255, 255, 190))
    arrow_col = (16, 185, 129, 255) if is_positive else (244, 63, 94, 255)
    draw.line([(ccx, ccy + 10), (ccx, ccy - cr + 5)], fill=arrow_col, width=3)
    draw.ellipse([(ccx - 3, ccy - cr + 2), (ccx + 3, ccy - cr + 8)], fill=arrow_col)

    return Image.alpha_composite(vis, ov).convert("RGB")


def pil_to_base64(img: Image.Image, max_side: int = 340) -> str:
    if img.width > max_side:
        img = img.resize((max_side, max_side), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=86)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def write_kaggle_notebook(out_path: Path) -> None:
    """Write a ready-to-run Kaggle / Colab YOLOv11 training notebook for Phase 2."""
    cells = [
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "# 🛰️ Manara Satellite Mosque Detector — YOLOv11 Training (Phase 2)\n",
                "Upload `mosque_dataset.zip` as a Kaggle Dataset (e.g. `mosque-dataset`), enable **GPU T4 x2**, and run all cells!"
            ],
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "!pip install -q ultralytics\n",
                "from pathlib import Path\n",
                "import yaml\n",
                "from ultralytics import YOLO\n",
                "\n",
                "# Locate dataset root automatically on Kaggle or Colab\n",
                "candidates = list(Path('/kaggle/input').rglob('data.yaml')) if Path('/kaggle/input').exists() else list(Path('.').rglob('data.yaml'))\n",
                "src_yaml = candidates[0]\n",
                "dataset_root = src_yaml.parent.resolve()\n",
                "print('Found dataset at:', dataset_root)\n",
                "\n",
                "# Write writable data.yaml in working dir pointing to dataset_root\n",
                "work_yaml = Path('mosque_data_runtime.yaml')\n",
                "work_yaml.write_text(yaml.safe_dump({\n",
                "    'path': str(dataset_root),\n",
                "    'train': 'train/images',\n",
                "    'val': 'val/images',\n",
                "    'nc': 1,\n",
                "    'names': {0: 'mosque'},\n",
                "}))\n",
                "\n",
                "# Train YOLOv11-Small on Qibla-Normalized 512x512 Tiles\n",
                "model = YOLO('yolo11s.pt')\n",
                "results = model.train(\n",
                "    data=str(work_yaml),\n",
                "    epochs=80,\n",
                "    imgsz=512,\n",
                "    batch=32,\n",
                "    degrees=0.0,   # Keep Qibla pointing straight UP!\n",
                "    fliplr=0.5,    # Horizontal flip preserves Qibla axis\n",
                "    flipud=0.5,    # Vertical flip preserves Qibla axis\n",
                "    mosaic=0.5,\n",
                ")"
            ],
        },
    ]
    nb = {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.11.0"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    out_path.write_text(json.dumps(nb, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main Pipeline Execution
# ---------------------------------------------------------------------------


def main() -> None:
    t0 = time.time()
    print("=" * 78)
    print("STEPS 1.2, 1.3 & 2.1: BUILDING QIBLA-ROTATED YOLO DATASET + HARD NEGATIVES")
    print("=" * 78)

    # 1. Load Saudi Regions & Boundary
    regions_fc = json.loads((ROOT_DIR / "sa_regions.geojson").read_text(encoding="utf-8"))
    regions = []
    for feat in regions_fc["features"]:
        geom = shape(feat["geometry"])
        regions.append(
            (
                feat["properties"]["code"],
                feat["properties"]["name_en"],
                feat["properties"]["name"],
                prep(geom),
                geom.bounds,
            )
        )
    regions.sort(key=lambda r: r[0])

    sa_geom = shape(json.loads((ROOT_DIR / "sa_boundary.geojson").read_text(encoding="utf-8"))["geometry"])
    sa_prep = prep(sa_geom)
    sa_bounds = sa_geom.bounds

    # 2. Build 68,525-mosque proximity guard & polygon neighbor index
    print("1. Indexing all 68,525 OSM & KAUST mosques for multi-box & hard-negative safety...")
    prox_index, poly_grid = build_all_mosques_index()

    # 3. Select 1,400 stratified positive mosques across all 13 Saudi regions
    print("2. Selecting 1,400 stratified regional positive mosques from Step 1.1...")
    positives = select_1400_positives(poly_grid)
    exact_count = sum(1 for p in positives if p["category"] in ("osm_way_polygon", "osm_pbf_building_match"))
    multi_box_count = sum(1 for p in positives if len(p["yolo_lines"]) > 1)
    print(
        f"   Selected {len(positives):,} positives across 13 regions "
        f"({exact_count:,} exact polygon footprints [{exact_count / len(positives) * 100:.1f}%], "
        f"{multi_box_count} multi-mosque patches)."
    )

    # 4. Mine 600 Saudi Hard Negatives (30% of dataset)
    print("3. Preparing 600 Saudi Hard Negatives (>= 260m from any known/suggested mosque)...")
    hard_negatives = load_or_mine_hard_negatives(regions, sa_prep, sa_bounds, prox_index)

    # 5. Stratified 80/20 Train / Val Split (preserving region & positive/negative category balance)
    rng = random.Random(20261106)
    strata: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for item in positives + hard_negatives:
        strata[(item["source"], item["region_code"])].append(item)

    all_records: list[dict] = []
    for _key, group in sorted(strata.items()):
        rng.shuffle(group)
        n_val = int(round(len(group) * VAL_FRACTION))
        for idx, item in enumerate(group):
            split = "val" if idx < n_val else "train"
            all_records.append({**item, "split": split})

    # Prepare clean YOLO folder tree
    for split in ("train", "val"):
        (DATASET_DIR / split / "images").mkdir(parents=True, exist_ok=True)
        (DATASET_DIR / split / "labels").mkdir(parents=True, exist_ok=True)

    n_train = sum(1 for r in all_records if r["split"] == "train")
    n_val = sum(1 for r in all_records if r["split"] == "val")
    print(
        f"4. Downloading & Qibla-rotating {len(all_records):,} borderless 512x512 patches "
        f"({n_train:,} train / {n_val:,} val)..."
    )

    # Thread-local HTTP sessions for polite connection pooling
    import threading
    thread_local = threading.local()

    def get_session() -> requests.Session:
        if not hasattr(thread_local, "session"):
            thread_local.session = make_http_session()
        return thread_local.session

    def export_one(rec: dict) -> tuple[bool, str, dict]:
        split = rec["split"]
        img_path = DATASET_DIR / split / "images" / f"{rec['id']}.jpg"
        lbl_path = DATASET_DIR / split / "labels" / f"{rec['id']}.txt"

        # Resumable: skip network if valid image & label already exist on disk
        if img_path.exists() and img_path.stat().st_size > 4000 and lbl_path.exists():
            return True, "cached", rec

        try:
            patch = fetch_borderless_qibla_patch(
                rec["lat"], rec["lon"], rec["qibla_bearing"], get_session(), ZOOM, PATCH_SIZE
            )
            if _is_placeholder_tile(patch):
                return False, "placeholder", rec
            patch.save(img_path, format="JPEG", quality=90)
            lbl_text = "\n".join(rec["yolo_lines"]) + ("\n" if rec["yolo_lines"] else "")
            lbl_path.write_text(lbl_text, encoding="utf-8")
            return True, "ok", rec
        except Exception as exc:
            return False, str(exc), rec

    completed = 0
    succeeded: list[dict] = []
    failed: list[tuple[str, dict]] = []
    t_dl = time.time()

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(export_one, r) for r in all_records]
        for fut in as_completed(futures):
            ok, msg, rec = fut.result()
            completed += 1
            if ok:
                succeeded.append(rec)
            else:
                failed.append((msg, rec))
            if completed % 250 == 0 or completed == len(all_records):
                elapsed = time.time() - t_dl
                rate = completed / max(0.1, elapsed)
                print(
                    f"   Progress: {completed:4d}/{len(all_records)} patches "
                    f"({len(succeeded)} saved, {len(failed)} skipped) — {rate:.1f} patches/sec"
                )

    # 6. Write data.yaml, manifest.json, Kaggle notebook, and mosque_dataset.zip
    data_yaml_text = (
        "# Manara Saudi Mosque Satellite Object Detection Dataset (Zoom 19, 512x512, Qibla-Normalized)\n"
        "train: train/images\n"
        "val: val/images\n"
        "nc: 1\n"
        "names:\n"
        "  0: mosque\n"
    )
    (DATASET_DIR / "data.yaml").write_text(data_yaml_text, encoding="utf-8")

    train_pos = sum(1 for r in succeeded if r["split"] == "train" and r["source"] != "hard_negative")
    train_neg = sum(1 for r in succeeded if r["split"] == "train" and r["source"] == "hard_negative")
    val_pos = sum(1 for r in succeeded if r["split"] == "val" and r["source"] != "hard_negative")
    val_neg = sum(1 for r in succeeded if r["split"] == "val" and r["source"] == "hard_negative")

    dataset_manifest = {
        "total_patches": len(succeeded),
        "train_patches": train_pos + train_neg,
        "val_patches": val_pos + val_neg,
        "train_positives": train_pos,
        "train_hard_negatives": train_neg,
        "val_positives": val_pos,
        "val_hard_negatives": val_neg,
        "hard_negative_pct": round((train_neg + val_neg) / max(1, len(succeeded)) * 100, 1),
        "zoom": ZOOM,
        "patch_size_px": PATCH_SIZE,
        "qibla_normalized_up_0_deg": True,
        "borderless_rotation": True,
        "category_counts": dict(collections.Counter(r["category"] for r in succeeded)),
        "region_counts": dict(sorted(collections.Counter(r["region_code"] for r in succeeded).items())),
    }
    (DATASET_DIR / "dataset_manifest.json").write_text(
        json.dumps(dataset_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    nb_path = ROOT_DIR / "poc_satellite_output" / "train_yolov11_kaggle.ipynb"
    write_kaggle_notebook(nb_path)

    print(f"5. Packaging {DATASET_ZIP_PATH.name} for Kaggle / Google Colab upload...")
    with zipfile.ZipFile(DATASET_ZIP_PATH, "w", compression=zipfile.ZIP_STORED) as zf:
        for file_path in sorted(DATASET_DIR.rglob("*")):
            if file_path.is_file():
                arcname = Path("mosque_dataset") / file_path.relative_to(DATASET_DIR)
                zf.write(file_path, arcname.as_posix())

    zip_mb = DATASET_ZIP_PATH.stat().st_size / (1024 * 1024)
    print(f"   Created {DATASET_ZIP_PATH} ({zip_mb:.1f} MB).")

    # 7. Build Visual Verification HTML Report (Borderless Qibla Positives + Hard Negatives)
    print("6. Rendering visual verification report for Steps 1.2, 1.3 & 2.1...")
    pos_samples = []
    seen_reg = set()
    for r in succeeded:
        if r["source"] != "hard_negative" and r["region_code"] not in seen_reg:
            seen_reg.add(r["region_code"])
            pos_samples.append(r)
            if len(pos_samples) >= 8:
                break

    neg_samples = []
    for cat in ("roundabout", "school_courtyard", "mall_large_roof", "highway_interchange", "desert_terrain"):
        cands = [r for r in succeeded if r["category"] == cat]
        neg_samples.extend(cands[:2])

    def build_card(rec: dict) -> str:
        img_path = DATASET_DIR / rec["split"] / "images" / f"{rec['id']}.jpg"
        img = Image.open(img_path).convert("RGB")
        is_pos = rec["source"] != "hard_negative"
        ann = annotate_yolo_patch(img, rec["yolo_lines"], is_pos)
        b64 = pil_to_base64(ann, 340)
        badge = (
            f'<span class="badge pos">POSITIVE · {rec["region_code"]}</span>'
            if is_pos
            else f'<span class="badge neg">HARD NEGATIVE · {rec["category"]}</span>'
        )
        lbl_str = " | ".join(rec["yolo_lines"]) if rec["yolo_lines"] else "(empty .txt — background)"
        return f"""
        <div class="card">
          <img src="{b64}" alt="{rec['id']}" />
          <div class="card-body">
            <div class="row">{badge}<span class="split">{rec['split'].upper()}</span></div>
            <h3>{rec['name']}</h3>
            <p class="coords">📍 {rec['lat']:.5f}, {rec['lon']:.5f} · Qibla Rotated: -{rec['qibla_bearing']}° → 0° UP</p>
            <code>{lbl_str}</code>
          </div>
        </div>
        """

    pos_cards = "".join(build_card(r) for r in pos_samples)
    neg_cards = "".join(build_card(r) for r in neg_samples[:8])

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Steps 1.2, 1.3 & 2.1 — Qibla-Normalized YOLOv11 Dataset</title>
  <style>
    body {{ font-family: system-ui, -apple-system, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 32px; }}
    .container {{ max-width: 1280px; margin: 0 auto; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; }}
    h2 {{ margin-top: 32px; border-bottom: 1px solid #334155; padding-bottom: 8px; }}
    .sub {{ color: #94a3b8; margin-bottom: 24px; line-height: 1.5; }}
    .stats {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 24px; }}
    .stat {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 16px 20px; flex: 1; min-width: 180px; }}
    .val {{ font-size: 26px; font-weight: 700; color: #38bdf8; }}
    .lbl {{ font-size: 13px; color: #94a3b8; margin-top: 4px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(290px, 1fr)); gap: 18px; }}
    .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; overflow: hidden; }}
    .card img {{ width: 100%; display: block; border-bottom: 1px solid #334155; }}
    .card-body {{ padding: 12px 14px; }}
    .row {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }}
    .badge {{ font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 999px; }}
    .pos {{ background: rgba(16, 185, 129, 0.16); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.4); }}
    .neg {{ background: rgba(244, 63, 94, 0.16); color: #fb7185; border: 1px solid rgba(244, 63, 94, 0.4); }}
    .split {{ font-size: 11px; color: #94a3b8; font-weight: 600; }}
    .card h3 {{ margin: 4px 0; font-size: 15px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    .coords {{ margin: 4px 0 8px; font-size: 12px; color: #94a3b8; }}
    code {{ display: block; background: #0f172a; padding: 6px 8px; border-radius: 6px; font-size: 11px; color: #a7f3d0; overflow-x: auto; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>🛰️ Phase 1 Complete — Borderless Qibla-Normalized YOLOv11 Dataset</h1>
    <p class="sub">
      <code>mosque_dataset.zip</code> ({zip_mb:.1f} MB) · {len(succeeded):,} Zoom-19 (512×512) patches ·
      Zero black rotation borders · Qibla strictly UP (0°) · 30% Saudi Hard Negatives.
    </p>
    <div class="stats">
      <div class="stat"><div class="val">{len(succeeded):,}</div><div class="lbl">Total 512×512 Patches</div></div>
      <div class="stat"><div class="val">{train_pos + train_neg:,} / {val_pos + val_neg:,}</div><div class="lbl">Train / Val Split (80/20)</div></div>
      <div class="stat"><div class="val">{train_pos + val_pos:,}</div><div class="lbl">Qibla-Aligned Mosque Positives</div></div>
      <div class="stat"><div class="val">{train_neg + val_neg:,} ({dataset_manifest['hard_negative_pct']}%)</div><div class="lbl">Verified Mosque-Free Hard Negatives</div></div>
      <div class="stat"><div class="val">{zip_mb:.1f} MB</div><div class="lbl">mosque_dataset.zip Size</div></div>
    </div>

    <h2>✅ Step 1.2 — Borderless Qibla-Normalized Positive Patches (Prayer Walls Horizontal/Vertical)</h2>
    <div class="grid">{pos_cards}</div>

    <h2>🛡️ Step 1.3 — Saudi Hard Negatives (Roundabouts, Schools, Malls, Interchanges, Desert)</h2>
    <div class="grid">{neg_cards}</div>
  </div>
</body>
</html>
"""
    REPORT_PATH.write_text(html, encoding="utf-8")

    print(f"\nDone in {(time.time() - t0) / 60.0:.1f} min!")
    print(f"   - YOLO Dataset Folder:  {DATASET_DIR}")
    print(f"   - Kaggle Upload Zip:    {DATASET_ZIP_PATH} ({zip_mb:.1f} MB)")
    print(f"   - Kaggle Notebook:      {nb_path}")
    print(f"   - Visual HTML Report:   {REPORT_PATH}")


if __name__ == "__main__":
    main()
