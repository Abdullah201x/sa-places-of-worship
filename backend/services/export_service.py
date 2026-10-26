"""
Export service supporting CSV, GeoJSON, and MapRoulette formats.
"""

import csv
import io
import json
from typing import Any, Dict, List
from backend.services.data_service import get_quality_issues


class ExportService:
    @staticmethod
    def to_csv(features: List[Dict[str, Any]]) -> str:
        """Generates UTF-8 CSV string (with BOM) for Excel compatibility."""
        output = io.StringIO()
        # UTF-8 BOM
        output.write("\ufeff")

        writer = csv.writer(output)
        writer.writerow([
            "osm_type",
            "osm_id",
            "name_ar",
            "name_en",
            "religion",
            "denomination",
            "building",
            "amenity",
            "lat",
            "lon",
            "area_m2",
            "qibla_dev_deg",
            "issues",
            "edited_at",
            "version",
        ])

        for feat in features:
            p = feat.get("properties", {})
            coords = feat.get("geometry", {}).get("coordinates", [0, 0])
            lon, lat = coords[0], coords[1]
            issues = [iss["id"] for iss in get_quality_issues(p)]

            anom = p.get("ml_anomaly")
            qibla_dev = anom.get("qibla_dev", "") if isinstance(anom, dict) else ""

            writer.writerow([
                p.get("osm_type", "way"),
                p.get("osm_id", ""),
                p.get("name_original") or p.get("name") or "",
                p.get("name_en_original") or p.get("name_en") or "",
                p.get("religion", ""),
                p.get("denomination", ""),
                p.get("building", ""),
                p.get("amenity", ""),
                lat,
                lon,
                p.get("size_area_m2", ""),
                qibla_dev,
                ";".join(issues),
                p.get("edited_at", ""),
                p.get("version", ""),
            ])

        return output.getvalue()

    @staticmethod
    def to_geojson(features: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Wraps features into a GeoJSON FeatureCollection."""
        return {
            "type": "FeatureCollection",
            "features": features,
        }

    @staticmethod
    def to_maproulette(features: List[Dict[str, Any]]) -> str:
        """
        Generates line-delimited GeoJSON for MapRoulette challenge tasks,
        with instructions in Arabic and English for each task.
        """
        lines = []
        for feat in features:
            p = feat.get("properties", {})
            issues = get_quality_issues(p)
            issue_titles_ar = " / ".join(i["title_ar"] for i in issues)
            issue_titles_en = " / ".join(i["title_en"] for i in issues)

            task_feature = {
                "type": "Feature",
                "geometry": feat.get("geometry"),
                "properties": {
                    "osm_id": p.get("osm_id"),
                    "osm_type": p.get("osm_type"),
                    "name": p.get("name_original") or p.get("name") or "مسجد",
                    "instruction_ar": f"تحقق من المشاكل التالية في هذا المسجد: {issue_titles_ar}",
                    "instruction_en": f"Please verify and fix the following issues: {issue_titles_en}",
                },
            }
            lines.append(json.dumps(task_feature, ensure_ascii=False))

        return "\n".join(lines)
