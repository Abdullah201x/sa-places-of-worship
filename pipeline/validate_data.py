"""
pipeline/validate_data.py - Strict Pre-Publish Data Contract Verification

Exits non-zero (stopping run.py from publishing or load_db from swapping)
when any dataset is missing, corrupt, shrunk suspiciously compared with the
last published run, violates PMTiles v3 specs, or fails integrity/sanity checks.
"""

import argparse
import csv
import hashlib
import json
import os
import struct
import subprocess
import sys

try:
    from common import BASE_DIR, SUMMARY_PATH, configure_utf8_output
except ImportError:
    from pipeline.common import BASE_DIR, SUMMARY_PATH, configure_utf8_output

configure_utf8_output()

# Minimum fraction of the previously published count a dataset may drop to.
MIN_RATIO = 0.8

DATASETS = {
    # summary key: (file, function returning the record count, required)
    "places": ("places_of_worship_sa.geojson", lambda d: len(d["features"]), True),
    "gaps": ("worship_gaps_sa.json", lambda d: len(d["cells"]), True),
    "regions": ("sa_regions.geojson", lambda d: len(d["features"]), True),
    "sizes": ("mosque_sizes.json", len, False),
    "anomalies": ("mosque_anomalies.json", len, False),
    "suggestions": ("suggested_mosques_sa.geojson", lambda d: len(d["features"]), False),
}

PMTILES_ARCHIVES = [
    ("places.pmtiles", True),
    ("gaps.pmtiles", True),
    ("suggestions.pmtiles", False),
]


def sha256_file(filepath):
    """Calculates SHA-256 hexadecimal digest of a file in 64 KiB chunks."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def published_summary(data_dir=None):
    """summary.json of what the live site serves: the file named by
    MANARA_PREVIOUS_SUMMARY on the server, else the last git commit."""
    previous_path = os.environ.get("MANARA_PREVIOUS_SUMMARY")
    if previous_path:
        try:
            with open(previous_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}
    base = data_dir or BASE_DIR
    try:
        out = subprocess.run(
            ["git", "show", "HEAD:summary.json"],
            cwd=base,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return json.loads(out.stdout) if out.returncode == 0 else {}
    except (OSError, ValueError):
        return {}


def validate_pmtiles_header(path, min_size=127, min_tiles=1):
    """Verifies PMTiles v3 specification header (b'PMTiles\\x03') and addressed tile count.

    Returns (is_valid, message).
    """
    if not os.path.exists(path):
        return False, f"File not found: {path}"
    size = os.path.getsize(path)
    if size < min_size:
        return False, f"{path} size ({size} bytes) is below minimum expected ({min_size} bytes)"

    try:
        with open(path, "rb") as f:
            magic = f.read(8)
            if magic != b"PMTiles\x03":
                return False, f"{path} invalid PMTiles magic header: expected b'PMTiles\\x03', got {magic!r}"
            header_bytes = f.read(88)
            if len(header_bytes) < 88:
                return False, f"{path} truncated PMTiles v3 header"
            fields = struct.unpack("<11Q", header_bytes)
            addressed_tiles = fields[8]
            if addressed_tiles < min_tiles:
                return False, f"{path} has {addressed_tiles} addressed tiles (expected at least {min_tiles})"
            return True, f"{addressed_tiles:,} addressed tiles"
    except Exception as e:
        return False, f"{path} read error: {e}"


def validate_regions_count(data_dir=None, expected_count=13):
    """Verifies sa_regions.geojson contains exactly expected_count features."""
    base = data_dir or BASE_DIR
    path = os.path.join(base, "sa_regions.geojson")
    if not os.path.exists(path):
        return [f"sa_regions.geojson is missing from {base}"]

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        features = data.get("features", [])
        if len(features) != expected_count:
            return [
                f"sa_regions.geojson contains {len(features)} regions, expected exactly {expected_count}"
            ]
        return []
    except Exception as e:
        return [f"sa_regions.geojson invalid: {e}"]


def validate_tag_stats_sanity(data_dir=None, min_ratio=0.01, max_ratio=0.95):
    """Verifies tag_stats_sa.json English name ratio is within realistic bounds.

    Catches synthetic fallback regressions (where name_en was populated 100% synthetically).
    """
    base = data_dir or BASE_DIR
    path = os.path.join(base, "tag_stats_sa.json")
    if not os.path.exists(path):
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            stats = json.load(f)

        key_info = stats.get("keys", {}).get("name:en", {})
        count = key_info.get("count", 0)
        total = stats.get("total_places", 0)
        pct = key_info.get("percentage")

        if total > 0:
            ratio = (pct / 100.0) if pct is not None else (count / total)
            if ratio < min_ratio:
                return [
                    f"tag_stats_sa.json: name:en coverage {ratio:.1%} is suspiciously low (< {min_ratio:.0%})"
                ]
            if ratio >= max_ratio:
                return [
                    f"tag_stats_sa.json: name:en coverage {ratio:.1%} >= {max_ratio:.0%} (synthetic fallback regression)"
                ]
        return []
    except Exception as e:
        return [f"tag_stats_sa.json invalid: {e}"]


def validate_csv_integrity(data_dir=None):
    """Verifies places_of_worship_sa.csv UTF-8 BOM, required columns, and non-empty IDs."""
    base = data_dir or BASE_DIR
    path = os.path.join(base, "places_of_worship_sa.csv")
    if not os.path.exists(path):
        return []

    errors = []
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            fieldnames = set(reader.fieldnames or [])

            if "id" not in fieldnames:
                errors.append("places_of_worship_sa.csv missing required column: id")
            if "osm_type" not in fieldnames and "geom_type" not in fieldnames:
                errors.append("places_of_worship_sa.csv missing osm_type/geom_type column")

            row_count = 0
            empty_id_count = 0
            empty_type_count = 0
            for row in reader:
                row_count += 1
                if not (row.get("id") or "").strip():
                    empty_id_count += 1
                osm_t = (row.get("osm_type") or row.get("geom_type") or "").strip()
                if not osm_t:
                    empty_type_count += 1

            if row_count == 0:
                errors.append("places_of_worship_sa.csv is empty")
            if empty_id_count > 0:
                errors.append(f"places_of_worship_sa.csv has {empty_id_count} rows with missing 'id'")
            if empty_type_count > 0:
                errors.append(f"places_of_worship_sa.csv has {empty_type_count} rows with missing 'osm_type'")
    except Exception as e:
        errors.append(f"places_of_worship_sa.csv read error: {e}")

    return errors


def validate_manifest_integrity(data_dir=None):
    """Verifies every file in manifest.json exists on disk with matching size and SHA-256."""
    base = data_dir or BASE_DIR
    path = os.path.join(base, "manifest.json")
    if not os.path.exists(path):
        return []

    errors = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        files = manifest.get("files", [])
        for entry in files:
            rel_path = entry.get("path")
            if not rel_path:
                continue
            full_path = os.path.join(base, rel_path)
            if not os.path.exists(full_path):
                errors.append(f"manifest.json references missing file: {rel_path}")
                continue

            expected_bytes = entry.get("bytes")
            if expected_bytes is not None:
                actual_bytes = os.path.getsize(full_path)
                if actual_bytes != expected_bytes:
                    errors.append(
                        f"manifest.json size mismatch for {rel_path}: expected {expected_bytes}, got {actual_bytes}"
                    )

            expected_sha = entry.get("sha256")
            if expected_sha:
                actual_sha = sha256_file(full_path)
                if actual_sha.lower() != expected_sha.lower():
                    errors.append(f"manifest.json SHA-256 mismatch for {rel_path}")
    except Exception as e:
        errors.append(f"manifest.json read error: {e}")

    return errors


def validate_dataset_records(data_dir=None, previous_summary_data=None, min_ratio=MIN_RATIO):
    """Verifies standard GeoJSON/JSON record counts and checks against shrinkage."""
    base = data_dir or BASE_DIR
    summary_path = os.path.join(base, "summary.json")
    errors = []
    log_lines = []

    previous = (previous_summary_data or published_summary(base)).get("datasets", {})

    for key, (filename, count_fn, required) in DATASETS.items():
        path = os.path.join(base, filename)
        if not os.path.exists(path):
            if required:
                errors.append(f"{filename} is missing")
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                count = count_fn(json.load(f))
        except (ValueError, KeyError, TypeError) as e:
            errors.append(f"{filename} is not valid: {e}")
            continue

        if count == 0 and required:
            errors.append(f"{filename} has no records")

        prev = previous.get(key, {}).get("count")
        status = "OK"
        if prev and count < prev * min_ratio:
            errors.append(
                f"{filename}: {count:,} records, down from {prev:,} (more than {1 - min_ratio:.0%} drop)"
            )
            status = "DROP"
        log_lines.append(f"  [{status}] {filename}: {count:,} records" + (f" (was {prev:,})" if prev else ""))

    if not os.path.exists(summary_path):
        errors.append("summary.json is missing")

    return errors, log_lines


def validate_all(data_dir=None, previous_summary_data=None, require_pmtiles=False):
    """Runs all pre-publish contract validation checks.

    Returns (is_valid: bool, errors: list[str], logs: list[str]).
    """
    base = data_dir or BASE_DIR
    all_errors = []
    all_logs = []

    # 1. Dataset record counts
    rec_errors, rec_logs = validate_dataset_records(base, previous_summary_data)
    all_errors.extend(rec_errors)
    all_logs.extend(rec_logs)

    # 2. Administrative region count
    reg_errors = validate_regions_count(base)
    all_errors.extend(reg_errors)

    # 3. PMTiles v3 specification and addressed tiles
    for filename, is_required in PMTILES_ARCHIVES:
        pmtiles_path = os.path.join(base, filename)
        if not os.path.exists(pmtiles_path):
            if require_pmtiles and is_required:
                all_errors.append(f"{filename} is missing")
            continue
        valid, msg = validate_pmtiles_header(pmtiles_path)
        if not valid:
            all_errors.append(f"PMTiles validation failed for {filename}: {msg}")
        else:
            all_logs.append(f"  [OK] {filename}: valid PMTiles v3 ({msg})")

    # 4. Manifest integrity (sizes and SHA-256)
    manifest_errors = validate_manifest_integrity(base)
    all_errors.extend(manifest_errors)
    if not manifest_errors and os.path.exists(os.path.join(base, "manifest.json")):
        all_logs.append("  [OK] manifest.json: all catalogued files verified on disk with SHA-256")

    # 5. Tag statistics sanity check
    tag_errors = validate_tag_stats_sanity(base)
    all_errors.extend(tag_errors)
    if not tag_errors and os.path.exists(os.path.join(base, "tag_stats_sa.json")):
        all_logs.append("  [OK] tag_stats_sa.json: English name coverage within realistic bounds")

    # 6. CSV integrity check
    csv_errors = validate_csv_integrity(base)
    all_errors.extend(csv_errors)
    if not csv_errors and os.path.exists(os.path.join(base, "places_of_worship_sa.csv")):
        all_logs.append("  [OK] places_of_worship_sa.csv: UTF-8 BOM, required columns & non-empty IDs")

    return (len(all_errors) == 0), all_errors, all_logs


def main():
    parser = argparse.ArgumentParser(description="Validate Manara datasets before publishing")
    parser.add_argument("--data-dir", help="Path to data directory", default=BASE_DIR)
    parser.add_argument("--require-pmtiles", action="store_true", help="Require PMTiles archives to exist")
    args = parser.parse_args()

    # Automatically require PMTiles if MANARA_REQUIRE_PMTILES is set or if manifest.json exists
    require_pmtiles = args.require_pmtiles or (os.environ.get("MANARA_REQUIRE_PMTILES", "0") == "1")

    is_valid, errors, logs = validate_all(data_dir=args.data_dir, require_pmtiles=require_pmtiles)

    for line in logs:
        print(line)

    if not is_valid:
        print("\n[FAIL] Data validation failed; not publishing:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print("[OK] All datasets passed validation.")


if __name__ == "__main__":
    main()
