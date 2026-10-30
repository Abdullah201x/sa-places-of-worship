"""
Shared helpers for the data pipeline scripts.

Every script used to carry its own copy of find_pbf() with hard-coded
Windows paths; they now import from here instead.
"""

import datetime
import glob
import json
import math
import os
import re
import sys
import tempfile
import unicodedata

from shapely.geometry import Polygon, shape
from shapely.prepared import prep

# Where the datasets are read and written. On the server MANARA_DATA_DIR
# points at the pipeline's work directory; locally it defaults to the repo
# root, where the frontend's dev server picks the files up.
CODE_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.abspath(os.environ.get("MANARA_DATA_DIR") or os.path.join(CODE_DIR, ".."))
SUMMARY_PATH = os.path.join(BASE_DIR, "summary.json")

# Equirectangular scaling around KSA's ~24 deg N latitude, sufficient for
# local length/area calculations (not a true projection).
REF_LAT_RAD = math.radians(24.0)
M_PER_DEG_LAT = 110_574.0
M_PER_DEG_LON = 111_320.0 * math.cos(REF_LAT_RAD)

# Tags that make an OSM object a place of worship for this project.
from worship_tags import is_worship_tagged


def configure_utf8_output():
    """Arabic console output on Windows terminals."""
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass


def find_pbf(base_dir=BASE_DIR):
    """
    Locates the OSM extract. Order: $OSM_PBF, then this folder, then the
    sibling "update osm" folder used by the master updater. If several
    extracts are present the newest one wins.
    """
    env_path = os.environ.get("OSM_PBF")
    if env_path:
        if os.path.exists(env_path):
            return env_path
        sys.exit(f"OSM_PBF is set but '{env_path}' does not exist.")

    search_dirs = [base_dir, os.path.abspath(os.path.join(base_dir, "..", "update osm"))]
    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        matches = set(glob.glob(os.path.join(d, "*.pbf")))
        if matches:
            return max(matches, key=os.path.getmtime)
    sys.exit("No .osm.pbf file found. Put one in this folder or in '../update osm', or set OSM_PBF.")


def load_boundary(base_dir=BASE_DIR):
    """Returns (polygon, prepared polygon, bounds) for sa_boundary.geojson."""
    path = os.path.join(base_dir, "sa_boundary.geojson")
    try:
        with open(path, "r", encoding="utf-8") as f:
            poly = shape(json.load(f)["geometry"])
    except Exception as e:
        sys.exit(f"Error loading boundary {path}: {e}")
    return poly, prep(poly), poly.bounds


def ring_centroid(coords):
    """
    Representative (lon, lat) for a way's node list.

    A plain average of a closed way's nodes counts the first node twice and is
    pulled toward densely-noded edges; use the polygon centroid instead, or a
    point guaranteed inside the shape when the centroid falls outside it
    (L- and U-shaped buildings). Open ways fall back to the vertex mean.
    """
    if not coords:
        return None
    closed = len(coords) >= 4 and coords[0] == coords[-1]
    if closed:
        try:
            poly = Polygon(coords)
            if poly.is_valid and poly.area > 0:
                c = poly.centroid
                if not poly.contains(c):
                    c = poly.representative_point()
                return c.x, c.y
        except Exception:
            pass
        coords = coords[:-1]
    n = len(coords)
    return sum(c[0] for c in coords) / n, sum(c[1] for c in coords) / n


def to_metres(coords):
    return [(lon * M_PER_DEG_LON, lat * M_PER_DEG_LAT) for lon, lat in coords]


# ---------------------------------------------------------------------------
# Arabic names (ported from osm x wikidata/pipeline/arabic_normalizer.py and
# wikidata_fetcher.py; keep in sync with js/arabic.js)
# ---------------------------------------------------------------------------

_RE_TASHKEEL = re.compile(r"[ً-ٰٟ]")
_RE_TATWEEL = re.compile(r"ـ")
_RE_PUNCT = re.compile(r"[^\w\s؀-ۿ]", re.UNICODE)

# Whole-word mosque terms: matches مسجد / جامع / مصلى (optionally with ال)
# but not جامعة (university) or words that merely contain them.
RE_MOSQUE_NAME = re.compile(r"(?<![؀-ۿ])(ال)?(جامع|مسجد|مصلى)(?![؀-ۿ])")
RE_MOSQUE_NAME_EN = re.compile(r"\b(mosque|masjid|musalla)\b", re.IGNORECASE)


def normalize_arabic(text, strip_al=False):
    """
    Normalizes Arabic text for comparison: removes tashkeel/tatweel, unifies
    alef/taa marbuta/alef maqsura/hamza seats, lowercases Latin, and treats
    جامع and مسجد as synonyms.
    """
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", str(text).strip())
    s = _RE_TASHKEEL.sub("", s)
    s = _RE_TATWEEL.sub("", s)
    s = re.sub(r"[أإآٱ]", "ا", s)
    s = s.replace("ة", "ه").replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")

    words = []
    for w in s.split():
        w = _RE_PUNCT.sub("", w).lower()
        if not w:
            continue
        if strip_al and w.startswith("ال") and len(w) > 3:
            w = w[2:]
        if w in ("جامع", "مسجد"):
            w = "مسجد"
        words.append(w)
    return " ".join(words)


# Words that carry no identifying information in a mosque's name. Stored
# normalized (strip_al=True) so they compare directly with normalize_arabic().
GENERIC_NAME_WORDS = {
    "مسجد", "مصلي", "محراب", "جمعه", "بدون", "اسم", "بلا",
    "mosque", "masjid", "musalla", "jami", "jame", "prayer", "room",
    "place", "of", "worship", "unnamed", "no", "name",
}


def is_generic_mosque_name(name):
    """True for empty names and names made only of generic words/numbers
    ("مسجد", "المسجد", "جامع", "مسجد جامع", "مصلى", "Mosque", "مسجد 3")."""
    norm = normalize_arabic(name, strip_al=True)
    if not norm:
        return True
    return all(w in GENERIC_NAME_WORDS or w.isdigit() for w in norm.split())


# ---------------------------------------------------------------------------
# Qibla
# ---------------------------------------------------------------------------

KAABA_LAT = 21.422487
KAABA_LON = 39.826206


def calculate_qibla_azimuth(lat, lon):
    """Forward great-circle azimuth (degrees from north) from (lat, lon) to the Kaaba."""
    lat1, lon1 = math.radians(lat), math.radians(lon)
    lat2, lon2 = math.radians(KAABA_LAT), math.radians(KAABA_LON)
    dlon = lon2 - lon1
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def axis_deviation(axis_deg, qibla_deg):
    """
    Smallest angle (0-45) between a building axis and the Qibla line, treating
    the building's two perpendicular axes as equivalent.
    """
    diff = abs((axis_deg % 180.0) - (qibla_deg % 180.0)) % 90.0
    return min(diff, 90.0 - diff)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_json(path, obj):
    """
    Writes minified UTF-8 JSON atomically: a crash mid-write leaves the
    previous file in place instead of a truncated one that would then be
    committed and published.
    """
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def pbf_timestamp(pbf_path):
    """ISO timestamp of the OSM data in the extract (from its header), falling
    back to the file's modification time."""
    try:
        import osmium
        reader = osmium.io.Reader(pbf_path, osmium.osm.osm_entity_bits.NOTHING)
        try:
            stamp = reader.header().get("osmosis_replication_timestamp")
        finally:
            reader.close()
        if stamp:
            return stamp
    except Exception:
        pass
    mtime = datetime.datetime.fromtimestamp(os.path.getmtime(pbf_path), datetime.timezone.utc)
    return mtime.isoformat()


def read_summary():
    try:
        with open(SUMMARY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def update_summary(dataset, info, pbf_path=None):
    """
    Merges one dataset's stats into summary.json. Other datasets keep their
    previous entries, so running a single script never wipes the rest.
    The frontend uses updated_at as its cache-busting version.
    """
    summary = read_summary()
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    summary["updated_at"] = now.isoformat().replace("+00:00", "Z")
    if pbf_path:
        stamp = pbf_timestamp(pbf_path)
        summary["pbf_file"] = os.path.basename(pbf_path)
        summary["pbf_date"] = stamp[:10]
        # Full time of the OSM data, for the frontend's "data age" label.
        summary["pbf_timestamp"] = stamp
    summary.setdefault("datasets", {})[dataset] = dict(info, updated_at=summary["updated_at"])
    write_json(SUMMARY_PATH, summary)
