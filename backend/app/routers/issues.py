from typing import Literal
from fastapi import APIRouter, Depends, Query
from app.auth import get_optional_user
from app.database import get_db

router = APIRouter(prefix="/api/v1", tags=["issues"])

RULE_SEVERITIES = {
    "missing_amenity": "high",
    "missing_name": "medium",
    "missing_name_en": "medium",
    "missing_denom": "medium",
    "size_too_small": "low",
    "size_too_large": "low",
    "stale_data": "low",
    "building_yes": "medium",
    "mapped_as_node": "low",
    "ml_geometry_anomaly": "high",
    "duplicate_poi": "high",
    "outdated_tags": "low",
    "qibla_deviation": "high",
}


RuleId = Literal[
    "missing_amenity",
    "missing_name",
    "missing_name_en",
    "missing_denom",
    "size_too_small",
    "size_too_large",
    "stale_data",
    "building_yes",
    "mapped_as_node",
    "ml_geometry_anomaly",
    "duplicate_poi",
    "outdated_tags",
    "qibla_deviation",
]

KNOWN_RULE_IDS = frozenset(RULE_SEVERITIES.keys())


@router.get("/issues")
def get_issues(
    rule_id: RuleId | None = Query(None, description="Filter by rule ID"),
    region_code: str | None = Query(None, description="Filter by region code, e.g. SA-01"),
    severity: Literal["high", "medium", "low"] | None = Query(None, description="Filter by severity"),
    status: Literal["all", "unreviewed", "fixed", "skipped"] = Query("all", description="Review status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: dict | None = Depends(get_optional_user),
    conn=Depends(get_db),
):
    """
    List QA issues for places of worship across Saudi Arabia.
    Supports filtering by rule ID, region code, severity, and review status.
    """
    caller_uid = user["osm_uid"] if user else None

    # Check if pre-populated issues table has data
    has_issues_table = False
    with conn.cursor() as cur:
        try:
            cur.execute("SELECT 1 FROM issues LIMIT 1;")
            if cur.fetchone():
                has_issues_table = True
        except Exception:
            pass

    if has_issues_table:
        query = """
        SELECT
            i.rule_id,
            i.severity,
            i.osm_type,
            i.osm_id,
            p.name,
            p.name_en,
            p.religion,
            p.denomination,
            p.region_code,
            r.name AS region_name,
            ST_X(p.geom) AS lon,
            ST_Y(p.geom) AS lat,
            i.suggested_fix,
            rm.status AS review_status
        FROM issues i
        JOIN places p ON p.osm_type = i.osm_type AND p.osm_id = i.osm_id
        LEFT JOIN regions r ON r.code = p.region_code
        LEFT JOIN review_marks rm ON rm.osm_type = i.osm_type
                                 AND rm.osm_id = i.osm_id
                                 AND (%s::bigint IS NOT NULL AND rm.osm_uid = %s::bigint)
        WHERE (%s::text IS NULL OR i.rule_id = %s::text)
          AND (%s::text IS NULL OR i.region_code = %s::text)
          AND (%s::text IS NULL OR i.severity = %s::text)
          AND (
              %s::text = 'all'
              OR (%s::text = 'unreviewed' AND rm.status IS NULL)
              OR (%s::text = 'fixed' AND rm.status = 'fixed')
              OR (%s::text = 'skipped' AND rm.status = 'skipped')
          )
        ORDER BY i.osm_id ASC
        LIMIT %s OFFSET %s;
        """
        params = (
            caller_uid, caller_uid,
            rule_id, rule_id,
            region_code, region_code,
            severity, severity,
            status, status, status, status,
            limit, offset,
        )
    else:
        # Dynamic fallback on places table
        rule_conditions = {
            "missing_amenity": "(p.building = 'mosque' AND p.amenity != 'place_of_worship')",
            "missing_name": "(p.name = '' OR p.name_norm IN ('مسجد', 'جامع', 'مصلى'))",
            "missing_name_en": "(p.name != '' AND p.name_norm NOT IN ('مسجد', 'جامع', 'مصلى') AND (p.name_en = '' OR p.name = p.name_en))",
            "missing_denom": "(p.religion = 'muslim' AND (p.denomination IS NULL OR p.denomination IN ('unknown', '')))",
            "building_yes": "(p.religion = 'muslim' AND p.building = 'yes')",
            "mapped_as_node": "(p.geom_type = 'Point' AND p.osm_type = 'node')",
            "size_too_small": "(p.area_m2 IS NOT NULL AND p.area_m2 < 50)",
            "size_too_large": "(p.area_m2 IS NOT NULL AND p.area_m2 > 10000)",
            "duplicate_poi": "(p.poi_node_id IS NOT NULL)",
            "qibla_deviation": "(p.qibla_dev IS NOT NULL AND p.qibla_dev >= 20.0)",
            "ml_geometry_anomaly": "(p.anomaly_score IS NOT NULL AND p.anomaly_score < -0.1)",
        }

        active_cond = rule_conditions.get(rule_id, "true") if rule_id else "true"
        assigned_rule = rule_id or "missing_denom"
        assigned_sev = severity or RULE_SEVERITIES.get(assigned_rule, "medium")

        query = f"""
        SELECT
            %s::text AS rule_id,
            %s::text AS severity,
            p.osm_type,
            p.osm_id,
            p.name,
            p.name_en,
            p.religion,
            p.denomination,
            p.region_code,
            r.name AS region_name,
            ST_X(p.geom) AS lon,
            ST_Y(p.geom) AS lat,
            NULL::jsonb AS suggested_fix,
            rm.status AS review_status
        FROM places p
        LEFT JOIN regions r ON r.code = p.region_code
        LEFT JOIN review_marks rm ON rm.osm_type = p.osm_type
                                 AND rm.osm_id = p.osm_id
                                 AND (%s::bigint IS NOT NULL AND rm.osm_uid = %s::bigint)
        WHERE {active_cond}
          AND (%s::text IS NULL OR p.region_code = %s::text)
          AND (
              %s::text = 'all'
              OR (%s::text = 'unreviewed' AND rm.status IS NULL)
              OR (%s::text = 'fixed' AND rm.status = 'fixed')
              OR (%s::text = 'skipped' AND rm.status = 'skipped')
          )
        ORDER BY p.osm_id ASC
        LIMIT %s OFFSET %s;
        """
        params = (
            assigned_rule, assigned_sev,
            caller_uid, caller_uid,
            region_code, region_code,
            status, status, status, status,
            limit, offset,
        )

    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()

    issues_list = []
    for r in rows:
        d = dict(r)
        d["coordinates"] = [d.pop("lon"), d.pop("lat")]
        issues_list.append(d)

    return {
        "count": len(issues_list),
        "limit": limit,
        "offset": offset,
        "issues": issues_list,
    }
