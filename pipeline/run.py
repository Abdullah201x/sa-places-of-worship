"""
Server-side pipeline runner (the VPS replacement for the desktop updater).

    python run.py once [--force]   one update: fetch, process, validate, publish
    python run.py schedule         run `once` daily at MANARA_RUN_AT_UTC

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
  MANARA_RUN_AT_UTC   "23:30" (02:30 in Riyadh, after Geofabrik's daily update)
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
RUN_AT_UTC = os.environ.get("MANARA_RUN_AT_UTC", "23:30")
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
    ["validate_data.py"],
    ["load_db.py"],
]
STEP_TIMEOUT_S = 45 * 60

# What the frontend loads from /data/ (frontend/src/app.js).
PUBLISHED_FILES = [
    "summary.json",
    "places_of_worship_sa.geojson",
    "worship_gaps_sa.json",
    "sa_boundary.geojson",
    "sa_regions.geojson",
    "mosque_sizes.json",
    "mosque_anomalies.json",
    "suggested_mosques_sa.geojson",
]


def log(msg):
    print(f"[{datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d %H:%M:%S}Z] {msg}", flush=True)


# ---------------------------------------------------------------------------
# 1. The OSM extract
# ---------------------------------------------------------------------------

def replication_sequence(pbf_path):
    """Replication sequence number in the extract's header (None if absent)."""
    reader = osmium.io.Reader(pbf_path, osmium.osm.osm_entity_bits.NOTHING)
    try:
        seq = reader.header().get("osmosis_replication_sequence_number")
    finally:
        reader.close()
    return int(seq) if seq else None


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
        dest = os.path.join(staging, name)
        shutil.copy2(os.path.join(WORK_DIR, name), dest)
        precompress(dest)
    os.replace(staging, target)

    # Atomic swap: a relative symlink, so it resolves inside any container
    # that mounts the publish dir, wherever it is mounted.
    tmp_link = CURRENT_LINK + ".tmp"
    if os.path.lexists(tmp_link):
        os.remove(tmp_link)
    os.symlink(version, tmp_link)
    os.replace(tmp_link, CURRENT_LINK)
    log(f"Published {version}")

    # Keep the live version and the one before it (for a manual rollback).
    versions = sorted(d for d in os.listdir(PUBLISH_DIR)
                      if d.startswith("v") and os.path.isdir(os.path.join(PUBLISH_DIR, d))
                      and not d.endswith(".staging"))
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


def seconds_until(hhmm_utc):
    hour, minute = (int(x) for x in hhmm_utc.split(":"))
    now = datetime.datetime.now(datetime.timezone.utc)
    nxt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if nxt <= now:
        nxt += datetime.timedelta(days=1)
    return (nxt - now).total_seconds()


def schedule():
    log(f"Scheduler started; daily run at {RUN_AT_UTC} UTC")
    if not os.path.exists(CURRENT_LINK):
        log("Nothing published yet; running now")
        run_once()
    while True:
        wait = seconds_until(RUN_AT_UTC)
        log(f"Next run in {wait / 3600:.1f} h")
        time.sleep(wait)
        run_once()


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
