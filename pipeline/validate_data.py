"""
Sanity checks run after the pipeline and before anything is committed.

Exits non-zero (which stops run.py from publishing, or update_projects.py
from pushing) when a dataset is missing, unreadable, or has shrunk
suspiciously compared with the last published run, e.g. after a truncated PBF
download or a failed extract.
"""

import json
import os
import subprocess
import sys

from common import BASE_DIR, SUMMARY_PATH, configure_utf8_output

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


def published_summary():
    """summary.json of what the live site serves: the file named by
    MANARA_PREVIOUS_SUMMARY on the server, else the last git commit."""
    previous_path = os.environ.get("MANARA_PREVIOUS_SUMMARY")
    if previous_path:
        try:
            with open(previous_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}  # first run: nothing published yet
    try:
        out = subprocess.run(["git", "show", "HEAD:summary.json"], cwd=BASE_DIR,
                             capture_output=True, text=True, encoding="utf-8")
        return json.loads(out.stdout) if out.returncode == 0 else {}
    except (OSError, ValueError):
        return {}


def main():
    errors = []
    previous = published_summary().get("datasets", {})

    for key, (filename, count_fn, required) in DATASETS.items():
        path = os.path.join(BASE_DIR, filename)
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
        if prev and count < prev * MIN_RATIO:
            errors.append(f"{filename}: {count:,} records, down from {prev:,} (more than {1 - MIN_RATIO:.0%} drop)")
            status = "DROP"
        print(f"  [{status}] {filename}: {count:,} records" + (f" (was {prev:,})" if prev else ""))

    if not os.path.exists(SUMMARY_PATH):
        errors.append("summary.json is missing")

    if errors:
        print("\n[FAIL] Data validation failed; not publishing:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    print("[OK] All datasets passed validation.")


if __name__ == "__main__":
    main()
