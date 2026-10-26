"""
Pipeline status and data validation service.
"""

import datetime
import json
import os
import subprocess
from typing import Any, Dict, List
from backend.config import Config
from backend.database import get_db_connection


class PipelineService:
    @staticmethod
    def get_status() -> Dict[str, Any]:
        """Returns the status and metadata for all pipeline data files."""
        datasets = [
            ("places", Config.PLACES_GEOJSON),
            ("gaps", Config.GAPS_JSON),
            ("sizes", Config.MOSQUE_SIZES_JSON),
            ("anomalies", Config.MOSQUE_ANOMALIES_JSON),
            ("suggestions", Config.SUGGESTED_MOSQUES_GEOJSON),
            ("boundary", Config.SA_BOUNDARY_GEOJSON),
            ("summary", Config.SUMMARY_JSON),
        ]

        status = {}
        for name, path in datasets:
            exists = os.path.exists(path)
            size = os.path.getsize(path) if exists else 0
            mtime = os.path.getmtime(path) if exists else None
            mtime_str = datetime.datetime.fromtimestamp(mtime, datetime.timezone.utc).isoformat() if mtime else None
            status[name] = {
                "file": os.path.basename(path),
                "exists": exists,
                "size_bytes": size,
                "updated_at": mtime_str,
            }

        # Git commit info if available
        git_info = {}
        try:
            res = subprocess.run(
                ["git", "log", "-1", "--format=%H|%an|%s|%ci"],
                cwd=Config.BASE_DIR,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            if res.returncode == 0 and res.stdout.strip():
                parts = res.stdout.strip().split("|")
                git_info = {
                    "commit_hash": parts[0][:8],
                    "author": parts[1] if len(parts) > 1 else "",
                    "subject": parts[2] if len(parts) > 2 else "",
                    "date": parts[3] if len(parts) > 3 else "",
                }
        except Exception:
            pass

        return {
            "datasets": status,
            "git": git_info,
        }

    @staticmethod
    def run_validation() -> Dict[str, Any]:
        """Runs validation checks on all datasets and records result in database."""
        errors = []
        counts = {}

        checks = {
            "places": (Config.PLACES_GEOJSON, lambda d: len(d.get("features", [])), True),
            "gaps": (Config.GAPS_JSON, lambda d: len(d.get("cells", [])), True),
            "sizes": (Config.MOSQUE_SIZES_JSON, len, False),
            "anomalies": (Config.MOSQUE_ANOMALIES_JSON, len, False),
            "suggestions": (Config.SUGGESTED_MOSQUES_GEOJSON, lambda d: len(d.get("features", [])), False),
        }

        for name, (path, count_fn, required) in checks.items():
            if not os.path.exists(path):
                if required:
                    errors.append(f"{os.path.basename(path)} is missing")
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    cnt = count_fn(json.load(f))
                    counts[name] = cnt
                    if cnt == 0 and required:
                        errors.append(f"{os.path.basename(path)} has 0 records")
            except Exception as e:
                errors.append(f"{os.path.basename(path)} error: {str(e)}")

        is_valid = len(errors) == 0
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Record in DB
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO pipeline_runs (status, details, run_date)
                VALUES (?, ?, ?)
                """,
                ("success" if is_valid else "failed", json.dumps({"counts": counts, "errors": errors}), now_str),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

        return {
            "is_valid": is_valid,
            "errors": errors,
            "counts": counts,
            "validated_at": now_str,
        }
