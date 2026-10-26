"""
Statistics and analytics service.
"""

from typing import Any, Dict
from backend.services.data_service import get_data_service, get_quality_issues
from backend.services.review_service import ReviewService


class StatsService:
    _cached_stats: Dict[str, Any] = {}
    _cache_time: float = 0.0

    @classmethod
    def get_dashboard_stats(cls, force_refresh: bool = False) -> Dict[str, Any]:
        data_svc = get_data_service()
        places = data_svc.places
        total_places = len(places)

        religions: Dict[str, int] = {}
        denoms: Dict[str, int] = {}
        geom_types: Dict[str, int] = {"node": 0, "way": 0, "relation": 0}
        issues_count: Dict[str, int] = {
            "missing_amenity": 0,
            "missing_name": 0,
            "missing_name_en": 0,
            "missing_denom": 0,
            "size_too_small": 0,
            "size_too_large": 0,
            "stale_data": 0,
            "building_yes": 0,
            "mapped_as_node": 0,
            "ml_geometry_anomaly": 0,
            "qibla_deviation": 0,
            "duplicate_poi": 0,
        }

        places_with_issues = 0

        for feat in places:
            p = feat.get("properties", {})
            rel = p.get("religion", "unknown")
            religions[rel] = religions.get(rel, 0) + 1

            denom = p.get("denomination", "unknown")
            denoms[denom] = denoms.get(denom, 0) + 1

            gt = p.get("osm_type", "way")
            geom_types[gt] = geom_types.get(gt, 0) + 1

            # Issues
            issues = get_quality_issues(p)
            if issues:
                places_with_issues += 1
                for iss in issues:
                    iss_id = iss["id"]
                    if iss_id in issues_count:
                        issues_count[iss_id] += 1
                    else:
                        issues_count[iss_id] = 1

        review_stats = ReviewService.get_stats()

        # Gaps stats
        gaps = data_svc.gaps_list
        total_gaps = len(gaps)
        max_gap_score = max((c["gap_score"] for c in gaps), default=0.0)
        avg_gap_score = round(sum(c["gap_score"] for c in gaps) / total_gaps, 2) if total_gaps else 0.0

        return {
            "summary": data_svc.summary_data,
            "places": {
                "total": total_places,
                "by_type": geom_types,
                "by_religion": religions,
                "by_denomination": denoms,
                "with_quality_issues": places_with_issues,
            },
            "quality_issues": issues_count,
            "gaps": {
                "total_cells": total_gaps,
                "max_score": round(max_gap_score, 2),
                "avg_score": avg_gap_score,
            },
            "suggestions": {
                "total": len(data_svc.suggestions),
            },
            "reviews": review_stats,
        }
