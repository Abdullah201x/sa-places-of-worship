"""
Mosque detector dataset v5: de-biased, field-representative, spatially split.

Fixes the four defects diagnosed in the v1-v4 datasets:

1. Centre bias - 99% of v2 labels sat within 5% of the patch centre because every
   positive patch was centred on its mosque. v5 places the target mosque at a
   uniformly random position in the Qibla-rotated frame and labels *every* known
   footprint that falls inside the patch.
2. Easy negatives - v1-v4 negatives were desert / forest / terrain, or hand-picked
   roundabouts and malls. v5 adds "field" negatives: random patches in inhabited
   neighbourhoods and inside the very gap cells the sweeper scans, plus the
   human-confirmed false positives from active learning.
3. Synthetic labels - 697 "qibla_prior_box" squares (made-up geometry) are dropped.
   Only real building footprints (OSM ways, KAUST points matched to a PBF building,
   human-confirmed detections) become boxes.
4. Leaky validation - v1-v4 used a random 80/20 split, so neighbouring/overlapping
   tiles appeared in both train and val. v5 splits by 0.1 deg geographic blocks
   (~10 km) and discards patches that straddle blocks of different splits.

Label hygiene: a patch is rejected when it contains a *known* mosque point (OSM node,
KAUST/Wikidata point, or an 'unsure' review) that has no footprint to label it -
otherwise the model would be trained to call a real mosque "background".

All geometry is done in Web-Mercator global pixel space at zoom 19, reproducing
`scan_worship_gaps.fetch_borderless_patch` exactly (integer centre pixel, 740 px
window, CCW rotation by the Qibla bearing, centre 512 crop), so training patches
are byte-for-byte the same kind of image the sweeper feeds the model.

Output: Ultralytics OBB format
    poc_satellite_output/mosque_dataset_v5/{train,val,test}/{images,labels}
    poc_satellite_output/mosque_dataset_v5/manifest.jsonl   (per-patch metadata)
    poc_satellite_output/mosque_dataset_v5/dataset.yaml
    poc_satellite_output/mosque_dataset_v5.zip

Usage:
    python scripts/build_dataset_v5.py                   # full build
    python scripts/build_dataset_v5.py --splits test     # only held-out test blocks
    python scripts/build_dataset_v5.py --dry-run         # plan only, no downloads

Imagery providers (the sweeper scans both Esri and Mapbox, so the model must see both):
    --provider mix      train/val default: each patch is Esri or Mapbox at random (--mapbox-frac)
    --provider both     every patch rendered twice (paired); used for the test split so
                        per-provider metrics compare identical places and labels
    --provider esri | mapbox
Mapbox patches get an "_mb" id suffix; Esri ids are unsuffixed.

Train vs. test composition: the TEST split mirrors what the sweeper really scans (about a
quarter of its target gap cells are desert/highway with no settlement nearby), so its
scores are honest. TRAIN/VAL is tilted toward informative urban background. Gap-cell
negatives must have a known mosque within 1.5 km (i.e. inhabited), and pure
desert-terrain filler is dropped. Empty land still appears naturally inside urban patches.
The v5 build used:  --splits test  (defaults)  and  --splits train val --n-urban 2800 --n-gap 1600
"""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import math
import random
import shutil
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import requests
from PIL import Image
from requests.adapters import HTTPAdapter
from shapely.geometry import Point, Polygon, box
from urllib3.util.retry import Retry

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "pipeline"))
sys.path.insert(0, str(ROOT_DIR / "scripts"))

from common import calculate_qibla_azimuth, configure_utf8_output  # noqa: E402
from step1_1_generate_bboxes import (  # noqa: E402
    MAPBOX_TOKEN,
    TILES_CACHE_DIR,
    _fetch_raw_mapbox_tile,
    _is_placeholder_tile,
    fetch_single_tile,
    latlon_to_global_px,
)

configure_utf8_output()

OUT = ROOT_DIR / "poc_satellite_output"
STEP1_1 = OUT / "step1_1_bboxes"
DATASET_DIR = OUT / "mosque_dataset_v5"
ZIP_PATH = OUT / "mosque_dataset_v5.zip"
FEEDBACK_JSON = ROOT_DIR / "active_learning_feedback.json"
DETECTIONS_DIR = OUT / "phase3_detections"

ZOOM = 19
PATCH = 512
OUTER_HALF = 370
HALF = PATCH / 2.0
WORLD_PX = 256.0 * (2**ZOOM)

BLOCK_DEG = 0.1  # spatial split unit (~10 km)
SPLIT_FRACTIONS = (("train", 0.80), ("val", 0.10), ("test", 0.10))
SPLIT_SALT = "manara-v5"

# Label rules (pixels are ~0.27 m at Saudi latitudes)
MIN_VISIBLE_FRACTION = 0.35  # truncated footprint labelled if >=35% of it is in view
MIN_VISIBLE_PX2 = 600.0  # ~45 m^2 visible roof
AMBIGUOUS_PX2 = 1500.0  # partially visible, too big to ignore, too cut to label -> reject patch
EXPLAIN_RADIUS_M = 30.0  # a known mosque point within 30 m of a footprint is "explained"
TARGET_MARGIN_PX = 12.0  # keep the target's OBB this far inside the patch edge

# Default sample budget (per full build, before split filtering)
DEFAULT_N_URBAN = 2200
DEFAULT_N_GAP = 1400
DEFAULT_FP_VARIANTS = 3
MAX_TILE_RPS = 10.0  # polite rate limit for uncached tile downloads, per provider
DEFAULT_MAPBOX_FRAC = 0.5  # sweeper runs --provider both, i.e. 50/50
INHABITED_RADIUS_M = 1500.0  # train/val gap negatives need >=1 known mosque within this radius
TRAIN_SPLITS = ("train", "val")


# ---------------------------------------------------------------------------
# Projection helpers (global Web-Mercator pixels at zoom 19)
# ---------------------------------------------------------------------------


def global_px_to_latlon(gx: float, gy: float) -> tuple[float, float]:
    lon = gx / WORLD_PX * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * gy / WORLD_PX))))
    return lat, lon


def m_per_px(lat: float) -> float:
    return 156543.03392 * math.cos(math.radians(lat)) / (2**ZOOM)


@dataclass(frozen=True)
class Frame:
    """A Qibla-rotated 512x512 patch: integer global centre pixel + rotation angle."""

    ix: int
    iy: int
    angle: float  # degrees, CCW image rotation applied (= Qibla bearing)

    def to_patch(self, gx: float, gy: float) -> tuple[float, float]:
        dx, dy = gx - self.ix, gy - self.iy
        a = math.radians(self.angle)
        c, s = math.cos(a), math.sin(a)
        return HALF + dx * c + dy * s, HALF - dx * s + dy * c

    def to_global(self, px: float, py: float) -> tuple[float, float]:
        rx, ry = px - HALF, py - HALF
        a = math.radians(self.angle)
        c, s = math.cos(a), math.sin(a)
        return self.ix + rx * c - ry * s, self.iy + rx * s + ry * c

    @property
    def latlon(self) -> tuple[float, float]:
        return global_px_to_latlon(self.ix, self.iy)


def frame_at(lat: float, lon: float) -> Frame:
    gx, gy = latlon_to_global_px(lat, lon, ZOOM)
    return Frame(int(round(gx)), int(round(gy)), round(calculate_qibla_azimuth(lat, lon), 2))


def frame_placing(gx: float, gy: float, u: float, v: float) -> Frame:
    """Frame whose rotated patch shows global point (gx, gy) at patch pixel (u, v)."""
    lat, lon = global_px_to_latlon(gx, gy)
    angle = round(calculate_qibla_azimuth(lat, lon), 2)
    rx, ry = u - HALF, v - HALF
    a = math.radians(angle)
    c, s = math.cos(a), math.sin(a)
    dx, dy = rx * c - ry * s, rx * s + ry * c
    return Frame(int(round(gx - dx)), int(round(gy - dy)), angle)


# ---------------------------------------------------------------------------
# Spatial split
# ---------------------------------------------------------------------------


def block_of(lat: float, lon: float) -> tuple[int, int]:
    return int(math.floor(lat / BLOCK_DEG)), int(math.floor(lon / BLOCK_DEG))


def split_of_block(blk: tuple[int, int]) -> str:
    h = hashlib.sha1(f"{SPLIT_SALT}:{blk[0]}:{blk[1]}".encode()).hexdigest()
    r = int(h[:8], 16) / 0xFFFFFFFF
    acc = 0.0
    for name, frac in SPLIT_FRACTIONS:
        acc += frac
        if r < acc:
            return name
    return SPLIT_FRACTIONS[-1][0]


def split_of_frame(fr: Frame) -> str | None:
    """Split of the patch, or None when its corners fall in blocks of different splits."""
    splits = set()
    for px, py in ((0, 0), (PATCH, 0), (0, PATCH), (PATCH, PATCH), (HALF, HALF)):
        lat, lon = global_px_to_latlon(*fr.to_global(px, py))
        splits.add(split_of_block(block_of(lat, lon)))
    return splits.pop() if len(splits) == 1 else None


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------


@dataclass
class Footprint:
    fid: str
    source: str
    lat: float
    lon: float
    region: str
    ring: list[tuple[float, float]]  # global px
    cx: float = field(init=False)
    cy: float = field(init=False)

    def __post_init__(self) -> None:
        self.cx = sum(p[0] for p in self.ring) / len(self.ring)
        self.cy = sum(p[1] for p in self.ring) / len(self.ring)


class GridIndex:
    """Bucket items by global-pixel cell for fast 'what is near this patch' queries."""

    def __init__(self, cell_px: float = 512.0):
        self.cell = cell_px
        self.g: dict[tuple[int, int], list] = collections.defaultdict(list)

    def add(self, gx: float, gy: float, item) -> None:
        self.g[(int(gx // self.cell), int(gy // self.cell))].append(item)

    def near(self, gx: float, gy: float, radius_px: float):
        r = int(math.ceil(radius_px / self.cell))
        cx, cy = int(gx // self.cell), int(gy // self.cell)
        for i in range(cx - r, cx + r + 1):
            for j in range(cy - r, cy + r + 1):
                yield from self.g.get((i, j), ())


def _ring_from_record(rec: dict) -> list[tuple[float, float]]:
    """step1_1 records store the polygon in pixels of a patch centred (continuously) on rec lat/lon."""
    cgx, cgy = latlon_to_global_px(rec["lat"], rec["lon"], ZOOM)
    return [(cgx - HALF + x, cgy - HALF + y) for x, y in rec["bbox_data"]["patch_polygon_px"]]


def load_feedback() -> dict:
    if not FEEDBACK_JSON.exists():
        return {}
    return json.loads(FEEDBACK_JSON.read_text(encoding="utf-8"))


def load_footprints(feedback: dict) -> list[Footprint]:
    fps: list[Footprint] = []
    for rec in map(json.loads, (STEP1_1 / "osm_way_bboxes.jsonl").read_text(encoding="utf-8").splitlines()):
        fps.append(Footprint(rec["id"], "osm_way", rec["lat"], rec["lon"], rec["region_code"], _ring_from_record(rec)))

    idx = GridIndex()
    for f in fps:
        idx.add(f.cx, f.cy, f)
    n_dup = 0
    for rec in map(json.loads, (STEP1_1 / "kaust_regional_1300_bboxes.jsonl").read_text(encoding="utf-8").splitlines()):
        if rec.get("bbox_source") != "osm_pbf_building_match":
            continue  # drop synthetic qibla_prior_box squares
        ring = _ring_from_record(rec)
        f = Footprint(rec["id"], "kaust_pbf_match", rec["lat"], rec["lon"], rec["region_code"], ring)
        if any(math.hypot(o.cx - f.cx, o.cy - f.cy) < 40 for o in idx.near(f.cx, f.cy, 40)):
            n_dup += 1
            continue
        fps.append(f)
        idx.add(f.cx, f.cy, f)

    # Human-confirmed detections: model box (axis-aligned in the Qibla frame) is the best geometry we have.
    n_fb = 0
    for det_id, v in feedback.items():
        if v.get("status") != "positive":
            continue
        meta_path = DETECTIONS_DIR / f"{det_id}_meta.json"
        if not meta_path.exists():
            # Reviewed on the website (scripts/publish_ai_detections.py): published lon/lat footprint.
            ring_ll = v.get("footprint_lonlat")
            if ring_ll and len(ring_ll) >= 4:
                pts = ring_ll[:-1] if ring_ll[0] == ring_ll[-1] else ring_ll  # GeoJSON rings repeat the start
                ring = [latlon_to_global_px(la, lo, ZOOM) for lo, la in pts]
                fps.append(Footprint(f"feedback_{det_id}", "feedback_positive", v["lat"], v["lon"],
                                     v.get("region_code", ""), ring))
                n_fb += 1
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        x0, y0, x1, y1 = meta["box_xyxy"]
        gx, gy = latlon_to_global_px(meta["lat"], meta["lon"], ZOOM)
        fr = Frame(int(round(gx)), int(round(gy)), float(meta["qibla_bearing"]))
        ring = [fr.to_global(x, y) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
        fps.append(Footprint(f"feedback_{det_id}", "feedback_positive", meta["lat"], meta["lon"], v.get("region_code", ""), ring))
        n_fb += 1

    print(f"  footprints: {len(fps):,} (KAUST duplicates of OSM skipped: {n_dup}, feedback positives: {n_fb})")
    return fps


def load_known_points(feedback: dict) -> list[tuple[float, float, str]]:
    pts: list[tuple[float, float, str]] = []
    for path, tag in (("places_of_worship_sa.geojson", "osm"), ("suggested_mosques_sa.geojson", "kaust")):
        for f in json.loads((ROOT_DIR / path).read_text(encoding="utf-8"))["features"]:
            lon, lat = f["geometry"]["coordinates"][:2]
            pts.append((lat, lon, tag))
    for v in feedback.values():
        if v.get("status") in ("positive", "unsure"):
            pts.append((v["lat"], v["lon"], f"feedback_{v['status']}"))
    return pts


def load_gap_cells(min_urgency: float = 60.0, min_road: float = 1000.0, max_road: float = 12000.0) -> list[tuple[float, float]]:
    cells = []
    with open(ROOT_DIR / "worship_gaps_sa.csv", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if float(r["urgency_score"]) >= min_urgency and min_road <= float(r["road_length_m"]) <= max_road:
                cells.append((int(r["grid_x"]), int(r["grid_y"])))
    return cells


# ---------------------------------------------------------------------------
# Labelling a frame
# ---------------------------------------------------------------------------


@dataclass
class World:
    fp_index: GridIndex
    pt_index: GridIndex
    fp_polys: dict[str, Polygon]  # global-px polygons, for 'explained point' checks


def build_world(fps: list[Footprint], pts: list[tuple[float, float, str]]) -> World:
    fp_index, pt_index, polys = GridIndex(), GridIndex(), {}
    for f in fps:
        fp_index.add(f.cx, f.cy, f)
        polys[f.fid] = Polygon(f.ring).buffer(0)
    for lat, lon, tag in pts:
        gx, gy = latlon_to_global_px(lat, lon, ZOOM)
        pt_index.add(gx, gy, (gx, gy, tag))
    return World(fp_index, pt_index, polys)


PATCH_BOX = box(0, 0, PATCH, PATCH)
SEARCH_R = PATCH  # global px radius around frame centre that can reach the patch


def label_frame(fr: Frame, world: World, target: Footprint | None = None) -> dict | None:
    """
    Return {"labels": [...], "fids": [...]} for the frame, or None when the patch must be rejected
    (target not fully visible, ambiguous truncation, or an unlabelled known mosque in view).
    """
    labels, fids = [], []
    near_fps = list(world.fp_index.near(fr.ix, fr.iy, SEARCH_R + 400))
    for f in near_fps:
        poly = Polygon([fr.to_patch(gx, gy) for gx, gy in f.ring]).buffer(0)
        if poly.is_empty or not poly.intersects(PATCH_BOX):
            if target is not None and f.fid == target.fid:
                return None
            continue
        vis = poly.intersection(PATCH_BOX)
        frac = vis.area / max(poly.area, 1e-6)
        if target is not None and f.fid == target.fid:
            rect = poly.minimum_rotated_rectangle
            x0, y0, x1, y1 = rect.bounds
            m = TARGET_MARGIN_PX
            if x0 < m or y0 < m or x1 > PATCH - m or y1 > PATCH - m:
                return None
        elif frac < MIN_VISIBLE_FRACTION or vis.area < MIN_VISIBLE_PX2:
            if vis.area >= AMBIGUOUS_PX2:
                return None
            continue
        rect = vis.minimum_rotated_rectangle
        corners = list(rect.exterior.coords)[:4]
        if len(corners) < 4:
            continue
        labels.append(corners)
        fids.append(f.fid)

    # Reject if any known mosque point inside the patch is not explained by a footprint.
    for gx, gy, tag in world.pt_index.near(fr.ix, fr.iy, SEARCH_R):
        px, py = fr.to_patch(gx, gy)
        if not (-8 <= px <= PATCH + 8 and -8 <= py <= PATCH + 8):
            continue
        lat = global_px_to_latlon(gx, gy)[0]
        r_px = EXPLAIN_RADIUS_M / m_per_px(lat)
        p = Point(gx, gy)
        if not any(world.fp_polys[f.fid].distance(p) <= r_px for f in near_fps):
            return None

    return {"labels": labels, "fids": fids}


def obb_line(corners: list[tuple[float, float]]) -> str:
    vals = []
    for x, y in corners:
        vals += [min(1.0, max(0.0, x / PATCH)), min(1.0, max(0.0, y / PATCH))]
    return "0 " + " ".join(f"{v:.6f}" for v in vals)


# ---------------------------------------------------------------------------
# Sample planning
# ---------------------------------------------------------------------------


def plan_samples(args, fps, world, feedback, rng: random.Random) -> list[dict]:
    want = set(args.splits)
    plan: list[dict] = []
    stats = collections.Counter()

    def try_add(kind: str, fr: Frame, meta: dict, target: Footprint | None = None) -> bool:
        sp = split_of_frame(fr)
        if sp is None:
            stats[f"{kind}:straddles_split"] += 1
            return False
        if sp not in want:
            stats[f"{kind}:other_split"] += 1
            return False
        lab = label_frame(fr, world, target)
        if lab is None:
            stats[f"{kind}:rejected"] += 1
            return False
        lat, lon = fr.latlon
        plan.append({"kind": kind, "split": sp, "ix": fr.ix, "iy": fr.iy, "angle": fr.angle,
                     "lat": round(lat, 6), "lon": round(lon, 6), **lab, **meta})
        stats[f"{kind}:ok"] += 1
        return True

    # 1. Positives: every footprint once, at a uniformly random position.
    for f in fps:
        # extent of the footprint in its own Qibla frame decides how far it can move
        fr0 = frame_placing(f.cx, f.cy, HALF, HALF)
        pts = [fr0.to_patch(gx, gy) for gx, gy in f.ring]
        w = max(p[0] for p in pts) - min(p[0] for p in pts)
        h = max(p[1] for p in pts) - min(p[1] for p in pts)
        lo_u, hi_u = w / 2 + TARGET_MARGIN_PX + 2, PATCH - w / 2 - TARGET_MARGIN_PX - 2
        lo_v, hi_v = h / 2 + TARGET_MARGIN_PX + 2, PATCH - h / 2 - TARGET_MARGIN_PX - 2
        if lo_u > hi_u or lo_v > hi_v:
            stats["positive:too_large"] += 1
            continue
        for _ in range(12):
            u, v = rng.uniform(lo_u, hi_u), rng.uniform(lo_v, hi_v)
            fr = frame_placing(f.cx, f.cy, u, v)
            if try_add("positive", fr, {"target": f.fid, "target_source": f.source, "region": f.region,
                                        "target_offset_px": round(math.hypot(u - HALF, v - HALF), 1)}, f):
                break

    # 2. Urban field patches: random spot 150-700 m from a random known mosque point.
    all_pts = [p for cell in world.pt_index.g.values() for p in cell]
    for _ in range(args.n_urban * 6):
        if sum(1 for s in plan if s["kind"] == "urban") >= args.n_urban:
            break
        gx, gy, _tag = rng.choice(all_pts)
        lat = global_px_to_latlon(gx, gy)[0]
        d = rng.uniform(150, 700) / m_per_px(lat)
        th = rng.uniform(0, 2 * math.pi)
        lat2, lon2 = global_px_to_latlon(gx + d * math.cos(th), gy + d * math.sin(th))
        try_add("urban", frame_at(lat2, lon2), {})

    # 3. Gap-cell field patches: uniform inside the high-urgency cells the sweeper targets.
    cells = load_gap_cells()

    def inhabited(fr: Frame) -> bool:
        r_px = INHABITED_RADIUS_M / m_per_px(fr.latlon[0])
        return any(math.hypot(gx - fr.ix, gy - fr.iy) <= r_px for gx, gy, _ in world.pt_index.near(fr.ix, fr.iy, r_px))

    for _ in range(args.n_gap * 6):
        if sum(1 for s in plan if s["kind"] == "gap") >= args.n_gap:
            break
        cx, cy = rng.choice(cells)
        lon = (cx + rng.random()) * 0.004
        lat = (cy + rng.random()) * 0.004
        fr = frame_at(lat, lon)
        if split_of_frame(fr) in TRAIN_SPLITS and not inhabited(fr):
            stats["gap:uninhabited_skipped"] += 1
            continue
        try_add("gap", fr, {"gap_cell": f"{cx}_{cy}"})

    # 4. Human-confirmed false positives, each shown at several random positions.
    for det_id, v in feedback.items():
        if v.get("status") != "negative":
            continue
        gx, gy = latlon_to_global_px(v["lat"], v["lon"], ZOOM)
        for k in range(args.fp_variants):
            for _ in range(8):
                fr = frame_placing(gx, gy, rng.uniform(110, PATCH - 110), rng.uniform(110, PATCH - 110))
                if try_add("confirmed_fp", fr, {"source_det": det_id}):
                    break

    # 5. Legacy category hard negatives (roundabouts, schools, malls, terrain) - re-positioned.
    legacy = STEP1_1 / "hard_negatives_600.jsonl"
    if legacy.exists():
        for rec in map(json.loads, legacy.read_text(encoding="utf-8").splitlines()):
            gx, gy = latlon_to_global_px(rec["lat"], rec["lon"], ZOOM)
            fr = frame_placing(gx, gy, rng.uniform(100, PATCH - 100), rng.uniform(100, PATCH - 100))
            if rec.get("category") == "desert_terrain" and split_of_frame(fr) in TRAIN_SPLITS:
                stats["legacy_negative:desert_skipped"] += 1
                continue
            try_add("legacy_negative", fr, {"category": rec.get("category", "")})

    print("  planning stats:")
    for k in sorted(stats):
        print(f"    {k:<32} {stats[k]:>6}")
    return plan


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------


class RateLimiter:
    def __init__(self, rps: float):
        self.interval = 1.0 / rps
        self.lock = threading.Lock()
        self.next_t = 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            t = max(now, self.next_t)
            self.next_t = t + self.interval
        if t > now:
            time.sleep(t - now)


LIMITERS = {"esri": RateLimiter(MAX_TILE_RPS), "mapbox": RateLimiter(MAX_TILE_RPS)}


def fetch_tile(provider: str, z: int, x: int, y: int, session: requests.Session) -> Image.Image:
    """
    Esri: the shared fetcher (Esri ancestor-tile fallback in rural areas).
    Mapbox: strict - never falls back to Esri. `fetch_single_tile(provider="mapbox")` silently
    substitutes Esri on any Mapbox error and caches it under the Mapbox name; that would put
    Esri pixels into "Mapbox" training samples.
    """
    if provider == "esri":
        if not (TILES_CACHE_DIR / f"{z}_{x}_{y}.jpg").exists():
            LIMITERS["esri"].wait()
        return fetch_single_tile(z, x, y, session)

    for d in (0, 1, 2):
        az, ax, ay = z - d, x >> d, y >> d
        if not (TILES_CACHE_DIR / f"raw_mapbox_{az}_{ax}_{ay}.jpg").exists():
            LIMITERS["mapbox"].wait()
        img = _fetch_raw_mapbox_tile(az, ax, ay, session)  # raises on HTTP error
        if not _is_placeholder_tile(img):
            if d == 0:
                return img
            sub = 256 >> d
            sx, sy = (x % (1 << d)) * sub, (y % (1 << d)) * sub
            return img.crop((sx, sy, sx + sub, sy + sub)).resize((256, 256), Image.Resampling.LANCZOS)
    return img


def make_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=4, backoff_factor=0.6, status_forcelist=(429, 500, 502, 503, 504))
    s.mount("https://", HTTPAdapter(pool_connections=16, pool_maxsize=16, max_retries=retry))
    return s


def render_frame(fr: Frame, session: requests.Session, provider: str = "esri") -> Image.Image | None:
    """Identical pixels to scan_worship_gaps.fetch_borderless_patch for the same centre and angle."""
    ix, iy = fr.ix, fr.iy
    tx0, tx1 = (ix - OUTER_HALF) // 256, (ix + OUTER_HALF - 1) // 256
    ty0, ty1 = (iy - OUTER_HALF) // 256, (iy + OUTER_HALF - 1) // 256
    canvas = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            canvas.paste(fetch_tile(provider, ZOOM, tx, ty, session), ((tx - tx0) * 256, (ty - ty0) * 256))
    x_off, y_off = (ix - OUTER_HALF) - tx0 * 256, (iy - OUTER_HALF) - ty0 * 256
    crop = canvas.crop((x_off, y_off, x_off + 2 * OUTER_HALF, y_off + 2 * OUTER_HALF))
    if _is_placeholder_tile(crop):
        return None
    rot = crop.rotate(fr.angle, resample=Image.Resampling.BICUBIC, expand=False)
    m = OUTER_HALF - PATCH // 2
    return rot.crop((m, m, m + PATCH, m + PATCH))


def sample_id(s: dict) -> str:
    suffix = "_mb" if s.get("provider") == "mapbox" else ""
    return f"{s['kind']}_{s['ix']}_{s['iy']}{suffix}"


def write_sample(s: dict, session: requests.Session) -> bool:
    sid = sample_id(s)
    img_p = DATASET_DIR / s["split"] / "images" / f"{sid}.jpg"
    lbl_p = DATASET_DIR / s["split"] / "labels" / f"{sid}.txt"
    if not img_p.exists():
        img = render_frame(Frame(s["ix"], s["iy"], s["angle"]), session, s.get("provider", "esri"))
        if img is None:
            return False
        img.save(img_p, format="JPEG", quality=92)
    lbl_p.write_text("".join(obb_line(c) + "\n" for c in s["labels"]), encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--splits", nargs="+", default=["train", "val", "test"], choices=["train", "val", "test"])
    ap.add_argument("--n-urban", type=int, default=DEFAULT_N_URBAN, help="urban field patches (all splits)")
    ap.add_argument("--n-gap", type=int, default=DEFAULT_N_GAP, help="gap-cell field patches (all splits)")
    ap.add_argument("--fp-variants", type=int, default=DEFAULT_FP_VARIANTS)
    ap.add_argument("--provider", choices=["mix", "both", "esri", "mapbox"], default="mix")
    ap.add_argument("--mapbox-frac", type=float, default=DEFAULT_MAPBOX_FRAC, help="Mapbox share for --provider mix")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed", type=int, default=20261107)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-zip", action="store_true")
    args = ap.parse_args()

    # Field budgets are national; scale to the requested splits so --splits test stays small.
    share = sum(f for n, f in SPLIT_FRACTIONS if n in args.splits)
    args.n_urban = int(round(args.n_urban * share))
    args.n_gap = int(round(args.n_gap * share))

    rng = random.Random(args.seed)
    print("1. Loading reference data...")
    feedback = load_feedback()
    fps = load_footprints(feedback)
    pts = load_known_points(feedback)
    print(f"  known mosque points: {len(pts):,}")
    world = build_world(fps, pts)

    print("2. Planning samples...")
    plan = plan_samples(args, fps, world, feedback, rng)
    if args.provider in ("mapbox", "both", "mix") and not MAPBOX_TOKEN:
        sys.exit("MAPBOX_ACCESS_TOKEN not set (env or .env) - cannot render Mapbox patches")
    # Provider assignment uses its own RNG so the geometric plan is identical across providers.
    prng = random.Random(args.seed + 1)
    if args.provider == "both":
        plan = [{**s, "provider": p} for s in plan for p in ("esri", "mapbox")]
    else:
        for s in plan:
            s["provider"] = args.provider if args.provider != "mix" else (
                "mapbox" if prng.random() < args.mapbox_frac else "esri")
    print("  providers:", dict(collections.Counter(s["provider"] for s in plan)))
    by = collections.Counter((s["split"], s["kind"]) for s in plan)
    for (sp, kind), n in sorted(by.items()):
        print(f"    {sp:<6} {kind:<16} {n:>6}")
    n_pos_img = sum(1 for s in plan if s["labels"])
    print(f"  total {len(plan):,} patches ({n_pos_img:,} with >=1 mosque, {len(plan) - n_pos_img:,} background)")
    if args.dry_run:
        return

    print("3. Rendering patches...")
    for sp in args.splits:
        for sub in ("images", "labels"):
            (DATASET_DIR / sp / sub).mkdir(parents=True, exist_ok=True)
    TILES_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    session = make_session()
    done, failed = [], 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(write_sample, s, session): s for s in plan}
        for i, fut in enumerate(as_completed(futs), 1):
            s = futs[fut]
            try:
                ok = fut.result()
            except Exception as e:  # network errors etc.
                ok = False
                print(f"    ! {sample_id(s)}: {e}")
            if ok:
                done.append(s)
            else:
                failed += 1
            if i % 250 == 0 or i == len(plan):
                rate = i / max(time.time() - t0, 1e-6)
                print(f"    {i:,}/{len(plan):,} ({rate:.1f}/s, failed {failed})", flush=True)

    manifest = DATASET_DIR / "manifest.jsonl"
    keep = {}
    rebuilt = {(s["split"], s["provider"]) for s in plan}
    if manifest.exists():  # merge with splits/providers built in earlier runs
        for rec in map(json.loads, manifest.read_text(encoding="utf-8").splitlines()):
            if (rec["split"], rec.get("provider", "esri")) not in rebuilt:
                keep[rec["id"]] = rec
    for s in done:
        rec = {k: v for k, v in s.items() if k != "labels"}
        rec["id"] = sample_id(s)
        rec["n_labels"] = len(s["labels"])
        rec["labels_px"] = [[[round(x, 1), round(y, 1)] for x, y in c] for c in s["labels"]]
        keep[rec["id"]] = rec
    manifest.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in keep.values()), encoding="utf-8")

    (DATASET_DIR / "dataset.yaml").write_text(
        "# Manara mosque detector v5 - spatially split, de-biased (scripts/build_dataset_v5.py)\n"
        f"path: {DATASET_DIR.name}\ntrain: train/images\nval: val/images\ntest: test/images\n\nnames:\n  0: mosque\n",
        encoding="utf-8",
    )
    print(f"  wrote {len(done):,} patches ({failed} failed); manifest has {len(keep):,} records")

    # Ultralytics trains on every file in the folder, not on the manifest: remove patches
    # left over from an earlier plan for the split/provider combinations rebuilt here.
    current = {sample_id(s) for s in plan}
    stale = 0
    for sp in args.splits:
        for img in (DATASET_DIR / sp / "images").glob("*.jpg"):
            prov = "mapbox" if img.stem.endswith("_mb") else "esri"
            if (sp, prov) in rebuilt and img.stem not in current:
                img.unlink()
                (DATASET_DIR / sp / "labels" / f"{img.stem}.txt").unlink(missing_ok=True)
                stale += 1
    if stale:
        print(f"  removed {stale} stale patches from an earlier plan")

    if not args.no_zip and set(args.splits) == {"train", "val", "test"}:
        print("4. Zipping...")
        ZIP_PATH.unlink(missing_ok=True)
        with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_STORED) as zf:
            for p in DATASET_DIR.rglob("*"):
                if p.is_file():
                    zf.write(p, p.relative_to(DATASET_DIR.parent))
        print(f"  {ZIP_PATH} ({ZIP_PATH.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
