"""
Server-side pipeline runner (the VPS replacement for the desktop updater).

    python run.py once [--force]   one update: fetch, process, validate, publish
    python run.py schedule         check hourly for a new Geofabrik update and
                                   run `once` when there is one

One run:
  1. Keeps the OSM extract current. The first run downloads Geofabrik's
     public GCC extract once; later runs only apply Geofabrik's daily diffs
     with pyosmium-up-to-date (a few MB per day). Nothing is ever read in bulk
     from the OpenStreetMap API.
  2. Stops there if the extract did not change (unless --force), so the
     pipeline runs at most once per new Geofabrik update.
  3. Downloads the Wikidata suggestions source (conditional GET).
  4. Runs every pipeline step as its own process, so each step's memory is
     returned to the OS before the next one starts.
  5. Validates the results against what is currently published.
  6. Publishes atomically: the datasets (plus .br/.gz copies) go into a new
     versioned folder, then the `current` symlink is swapped to it. Caddy
     serves /data/* from `current`, so visitors never see a half-written set.
     The previous version is kept for rollback; older ones are deleted.

Environment (defaults suit the Docker image, pipeline/Dockerfile):
  MANARA_STATE_DIR    /state      extract, downloads, scratch work dir
  MANARA_PUBLISH_DIR  /published  shared with the web container
  MANARA_EXTRACT_URL  Geofabrik public GCC extract
  MANARA_WIKIDATA_URL osm-x-wikidata data/sa.json on GitHub
  MANARA_CHECK_EVERY_MIN  60      how often `schedule` looks for a new update

Geofabrik publishes the daily diff at no fixed time (seen from 20:45 to the
next day's 12:56 UTC), so `schedule` does not run at a set hour: it reads the
small state.txt of the extract's replication URL every hour and only starts a
run when its sequence number is ahead of the local extract's.
"""

import datetime
import gzip
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

import brotli
import osmium

CODE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.environ.get("MANARA_STATE_DIR", "/state")
PUBLISH_DIR = os.environ.get("MANARA_PUBLISH_DIR", "/published")
EXTRACT_URL = os.environ.get("MANARA_EXTRACT_URL",
                             "https://download.geofabrik.de/asia/gcc-states-latest.osm.pbf")
WIKIDATA_URL = os.environ.get("MANARA_WIKIDATA_URL",
                              "https://raw.githubusercontent.com/Abdullah201x/osm-x-wikidata/main/data/sa.json")
CHECK_EVERY_S = int(os.environ.get("MANARA_CHECK_EVERY_MIN", "60")) * 60
USER_AGENT = "Manara/1.0 (+https://manara.saudiosm.org)"

PBF_PATH = os.path.join(STATE_DIR, "gcc-states.osm.pbf")
WIKIDATA_PATH = os.path.join(STATE_DIR, "wikidata_sa.json")
WORK_DIR = os.path.join(STATE_DIR, "work")
LOCK_PATH = os.path.join(STATE_DIR, "run.lock")
STATUS_PATH = os.path.join(STATE_DIR, "status.json")
CURRENT_LINK = os.path.join(PUBLISH_DIR, "current")

# In order; each reads the previous steps' output from the work dir.
STEPS = [
    ["extract_sa_boundary.py", "--force"],
    ["extract_regions.py", "--force"],
    ["extract_places.py"],
    ["calculate_gaps.py"],
    ["calculate_mosque_sizes.py"],
    ["detect_geometry_anomalies.py"],
    ["import_wikidata_suggestions.py"],
    ["tag_stats.py"],
    # Overlays first: build_data_hub catalogues the .pmtiles they produce.
    ["build_overlays.py"],
    ["build_data_hub.py"],
    ["validate_data.py"],
    ["load_db.py"],
]
STEP_TIMEOUT_S = 45 * 60

# What the frontend loads from /data/ (frontend/src/app.js).
PUBLISHED_FILES = [
    "summary.json",
    "manifest.json",
    "places_of_worship_sa.geojson",
    "places_of_worship_sa.csv",
    "worship_gaps_sa.json",
    "worship_gaps_sa.csv",
    "sa_boundary.geojson",
    "sa_regions.geojson",
    "mosque_sizes.json",
    "mosque_anomalies.json",
    "suggested_mosques_sa.geojson",
    "suggested_mosques_sa.csv",
    "tag_stats_sa.json",
    "tags.json",
    "places.pmtiles",
    "gaps.pmtiles",
    "suggestions.pmtiles",
]


def log(msg):
    print(f"[{datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d %H:%M:%S}Z] {msg}", flush=True)


# ---------------------------------------------------------------------------
# 1. The OSM extract
# ---------------------------------------------------------------------------

def replication_header(pbf_path):
    """(sequence number, replication base URL) from the extract's header;
    either is None if absent."""
    reader = osmium.io.Reader(pbf_path, osmium.osm.osm_entity_bits.NOTHING)
    try:
        header = reader.header()
        seq = header.get("osmosis_replication_sequence_number")
        url = header.get("osmosis_replication_base_url")
    finally:
        reader.close()
    return (int(seq) if seq else None), (url or None)


def replication_sequence(pbf_path):
    """Replication sequence number in the extract's header (None if absent)."""
    return replication_header(pbf_path)[0]


def parse_state(text):
    """sequenceNumber from a replication state.txt (None if missing)."""
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "sequenceNumber" and value.strip().isdigit():
            return int(value.strip())
    return None


def remote_sequence(base_url):
    """The newest sequence number Geofabrik has published (one small GET)."""
    url = base_url.rstrip("/") + "/state.txt"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return parse_state(resp.read().decode("utf-8", "replace"))


def update_available():
    """True when Geofabrik has a newer update than the local extract, or when
    that can't be told (no extract yet, or the check failed), so run_once()
    decides with its own up-to-date check."""
    if not os.path.exists(PBF_PATH):
        return True
    try:
        local, base_url = replication_header(PBF_PATH)
        if local is None or not base_url:
            return True
        remote = remote_sequence(base_url)
    except Exception as e:  # noqa: BLE001 - fall back to a normal run
        log(f"Update check failed ({e}); running anyway")
        return True
    return remote is None or remote > local


def download(url, dest, etag_path=None):
    """Streams url to dest via a temp file. With etag_path, sends
    If-None-Match and returns False (dest untouched) on 304."""
    headers = {"User-Agent": USER_AGENT}
    if etag_path and os.path.exists(etag_path) and os.path.exists(dest):
        with open(etag_path, encoding="utf-8") as f:
            headers["If-None-Match"] = f.read().strip()
    req = urllib.request.Request(url, headers=headers)
    tmp = dest + ".part"
    try:
        with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as out:
            shutil.copyfileobj(resp, out, length=1 << 20)
            etag = resp.headers.get("ETag")
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return False
        raise
    os.replace(tmp, dest)
    if etag_path and etag:
        with open(etag_path, "w", encoding="utf-8") as f:
            f.write(etag)
    return True


def update_extract():
    """Returns True when the extract changed (or was first downloaded)."""
    if not os.path.exists(PBF_PATH):
        log(f"No extract yet; downloading {EXTRACT_URL} (one-time full download)")
        download(EXTRACT_URL, PBF_PATH)
        log(f"Downloaded {os.path.getsize(PBF_PATH) / 2**20:.0f} MiB, sequence {replication_sequence(PBF_PATH)}")
        return True

    before = replication_sequence(PBF_PATH)
    # Uses the replication URL in the file's header (Geofabrik's public
    # gcc-states-updates). Exit 0: up to date; 1: partially updated, more
    # available (run again); >1: failed, file untouched.
    for attempt in range(3):
        res = subprocess.run(["pyosmium-up-to-date", "-v", "--tmpdir", STATE_DIR, PBF_PATH])
        if res.returncode == 0:
            break
        if res.returncode > 1:
            raise RuntimeError(f"pyosmium-up-to-date failed (exit {res.returncode})")
        log("Partial update, fetching the rest")
    after = replication_sequence(PBF_PATH)
    log(f"Extract sequence {before} -> {after}")
    return after != before


# ---------------------------------------------------------------------------
# 2-5. Processing
# ---------------------------------------------------------------------------

def run_steps():
    shutil.rmtree(WORK_DIR, ignore_errors=True)
    os.makedirs(WORK_DIR)
    env = dict(
        os.environ,
        MANARA_DATA_DIR=WORK_DIR,
        OSM_PBF=PBF_PATH,
        MANARA_WIKIDATA_SOURCE=WIKIDATA_PATH,
        # validate_data.py compares counts with what is live now.
        MANARA_PREVIOUS_SUMMARY=os.path.join(CURRENT_LINK, "summary.json"),
        PYTHONUNBUFFERED="1",
    )
    for step in STEPS:
        log(f"Running {step[0]}")
        started = time.time()
        res = subprocess.run([sys.executable, os.path.join(CODE_DIR, step[0]), *step[1:]],
                             cwd=WORK_DIR, env=env, timeout=STEP_TIMEOUT_S)
        if res.returncode != 0:
            raise RuntimeError(f"{step[0]} failed (exit {res.returncode})")
        log(f"{step[0]} done in {time.time() - started:.0f}s")


# ---------------------------------------------------------------------------
# 6. Publishing
# ---------------------------------------------------------------------------

def precompress(path):
    # PMTiles are read with HTTP Range requests and their tiles are already
    # gzipped; a .br/.gz sibling would be served for byte ranges of the wrong
    # (compressed) file, so never create one.
    if path.endswith(".pmtiles"):
        return
    with open(path, "rb") as f:
        data = f.read()
    with open(path + ".br", "wb") as f:
        f.write(brotli.compress(data, quality=11))
    with gzip.open(path + ".gz", "wb", compresslevel=9) as f:
        f.write(data)


def publish():
    with open(os.path.join(WORK_DIR, "summary.json"), encoding="utf-8") as f:
        updated_at = json.load(f)["updated_at"]
    version = "v" + updated_at.replace("-", "").replace(":", "")
    target = os.path.join(PUBLISH_DIR, version)
    staging = target + ".staging"
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging)
    for name in PUBLISHED_FILES:
        src = os.path.join(WORK_DIR, name)
        if os.path.exists(src):
            dest = os.path.join(staging, name)
            shutil.copy2(src, dest)
            precompress(dest)

    reg_src = os.path.join(WORK_DIR, "by-region")
    if os.path.exists(reg_src):
        reg_dest = os.path.join(staging, "by-region")
        shutil.copytree(reg_src, reg_dest)
        for root, _, files in os.walk(reg_dest):
            for fname in files:
                if not (fname.endswith(".br") or fname.endswith(".gz")):
                    precompress(os.path.join(root, fname))

    os.replace(staging, target)

    # Atomic swap: a relative symlink, so it resolves inside any container
    # that mounts the publish dir, wherever it is mounted.
    tmp_link = CURRENT_LINK + ".tmp"
    if os.path.lexists(tmp_link):
        os.remove(tmp_link)
    os.symlink(version, tmp_link)
    os.replace(tmp_link, CURRENT_LINK)
    log(f"Published {version}")

    # Staging dirs are named per version, so one left by an interrupted run
    # (e.g. a redeploy mid-publish) is never reused: drop them.
    for d in os.listdir(PUBLISH_DIR):
        if d.endswith(".staging"):
            shutil.rmtree(os.path.join(PUBLISH_DIR, d), ignore_errors=True)

    # Keep the live version and the one before it (for a manual rollback).
    versions = sorted(d for d in os.listdir(PUBLISH_DIR)
                      if d.startswith("v") and os.path.isdir(os.path.join(PUBLISH_DIR, d)))
    for old in versions[:-2]:
        shutil.rmtree(os.path.join(PUBLISH_DIR, old), ignore_errors=True)
    return version


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def write_status(**fields):
    status = {}
    if os.path.exists(STATUS_PATH):
        with open(STATUS_PATH, encoding="utf-8") as f:
            status = json.load(f)
    status.update(fields)
    with open(STATUS_PATH + ".tmp", "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2)
    os.replace(STATUS_PATH + ".tmp", STATUS_PATH)


def acquire_lock():
    """One run at a time (a scheduled run and a manual one could overlap)."""
    try:
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        # A crashed run leaves the lock behind; it is stale after 3 hours.
        if time.time() - os.path.getmtime(LOCK_PATH) < 3 * 3600:
            return False
        os.remove(LOCK_PATH)
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    return True


def run_once(force=False):
    os.makedirs(STATE_DIR, exist_ok=True)
    os.makedirs(PUBLISH_DIR, exist_ok=True)
    if not acquire_lock():
        log("Another run is in progress; skipping")
        return True
    started = time.time()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        write_status(last_attempt=now)
        changed = update_extract()
        never_published = not os.path.exists(CURRENT_LINK)
        if not (changed or force or never_published):
            log("No new OSM data since the last run; nothing to do")
            write_status(last_result="no new data")
            return True
        if download(WIKIDATA_URL, WIKIDATA_PATH, etag_path=WIKIDATA_PATH + ".etag"):
            log("Downloaded a new Wikidata source")
        run_steps()
        version = publish()
        write_status(last_result="published", last_success=now, published_version=version,
                     duration_s=round(time.time() - started), last_error=None)
        return True
    except Exception as e:  # noqa: BLE001 - report every failure, keep the old data live
        log(f"FAILED: {e}; the previously published data stays live")
        write_status(last_result="failed", last_error=str(e))
        return False
    finally:
        os.remove(LOCK_PATH)


RETRY_FAILED_AFTER_S = 6 * 3600


def failed_run_due(status, now):
    """True when the last run failed at least RETRY_FAILED_AFTER_S ago. A run
    that fails after the diffs were applied leaves the extract up to date, so
    without a forced retry that update would never be published."""
    if status.get("last_result") != "failed" or not status.get("last_attempt"):
        return False
    attempt = datetime.datetime.fromisoformat(status["last_attempt"])
    return (now - attempt).total_seconds() >= RETRY_FAILED_AFTER_S


def read_status():
    try:
        with open(STATUS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def schedule():
    log(f"Scheduler started; checking for new Geofabrik updates every {CHECK_EVERY_S // 60} min")
    while True:
        now = datetime.datetime.now(datetime.timezone.utc)
        if not os.path.exists(CURRENT_LINK):
            log("Nothing published yet; running now")
            run_once()
        elif failed_run_due(read_status(), now):
            log("Retrying the last failed run")
            run_once(force=True)
        elif update_available():
            log("New Geofabrik update available")
            run_once()
        time.sleep(CHECK_EVERY_S)


def main():
    args = sys.argv[1:]
    if args[:1] == ["schedule"]:
        schedule()
    elif args[:1] == ["once"]:
        sys.exit(0 if run_once(force="--force" in args) else 1)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
