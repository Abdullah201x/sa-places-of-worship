"""
Data service managing in-memory spatial indexes, dataset loading, and queries.
"""

import json
import math
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from shapely.geometry import Point, box
from shapely.strtree import STRtree

from backend.config import Config
from common import is_generic_mosque_name, normalize_arabic


def osm_type_of(props: Dict[str, Any]) -> str:
    geom = props.get("geom_type")
    if geom == "Point":
        return "node"
    elif geom == "Relation":
        return "relation"
    return "way"


def get_quality_issues(
    props: Dict[str, Any],
    min_size_m2: float = 20.0,
    max_size_m2: float = 15000.0,
    qibla_threshold: float = 20.0,
) -> List[Dict[str, str]]:
    """Evaluates mapping quality issues for a place of worship."""
    issues = []

    # 1. Missing amenity tag
    if props.get("building") == "mosque" and props.get("amenity") != "place_of_worship":
        issues.append({
            "id": "missing_amenity",
            "title_ar": "مبنى مسجد بدون تصنيف (amenity=place_of_worship)",
            "title_en": "Building marked as mosque but missing amenity=place_of_worship"
        })

    # 2. Generic mosque name
    name_orig = props.get("name_original") or ""
    if is_generic_mosque_name(name_orig):
        issues.append({
            "id": "missing_name",
            "title_ar": 'اسم المسجد مفقود أو افتراضي (مثال: "مسجد")',
            "title_en": "Mosque name is missing or set to a generic default"
        })

    # 3. Missing English name
    clean_ar = (props.get("name_original") or "").strip()
    clean_en = (props.get("name_en_original") or "").strip()
    if not clean_en or (clean_ar and clean_ar == clean_en):
        issues.append({
            "id": "missing_name_en",
            "title_ar": "الاسم بالإنجليزية مفقود أو مطابق للاسم العربي",
            "title_en": "English name translation (name:en) is missing or identical to the Arabic name"
        })

    # 4. Missing denomination
    if props.get("religion") == "muslim" and (not props.get("denomination") or props.get("denomination") == "unknown"):
        issues.append({
            "id": "missing_denom",
            "title_ar": "المذهب غير محدد (سني/شيعي)",
            "title_en": "Denomination is unknown or unspecified"
        })

    # 5. Unusual building size
    size_m2 = props.get("size_area_m2")
    if isinstance(size_m2, (int, float)):
        if size_m2 < min_size_m2:
            issues.append({
                "id": "size_too_small",
                "title_ar": "مبنى المسجد أصغر من المعتاد بشكل ملحوظ — تحقق من حدود المبنى",
                "title_en": "Mosque building footprint looks too small — verify the building outline"
            })
        elif size_m2 > max_size_m2:
            issues.append({
                "id": "size_too_large",
                "title_ar": "مبنى المسجد أكبر من المعتاد بشكل ملحوظ — تحقق من حدود المبنى",
                "title_en": "Mosque building footprint looks too large — verify the building outline"
            })

    # 6. Stale data (version 1 and older than 5 years)
    edited_at = props.get("edited_at")
    if props.get("version") == 1 and edited_at:
        try:
            # Parse ISO date string
            clean_date = edited_at[:19]
            ts = time.mktime(time.strptime(clean_date, "%Y-%m-%dT%H:%M:%S"))
            if time.time() - ts > (5 * 365 * 24 * 3600):
                issues.append({
                    "id": "stale_data",
                    "title_ar": "لم يتم تعديل هذا العنصر منذ إضافته لأول مرة (بيانات قديمة)",
                    "title_en": "This entry has never been revisited since it was first mapped"
                })
        except Exception:
            pass

    # 7. building=yes on a mosque
    if props.get("religion") == "muslim" and props.get("building") == "yes":
        issues.append({
            "id": "building_yes",
            "title_ar": "مبنى مسجد مصنف كـ building=yes بدلاً من building=mosque",
            "title_en": "Mosque building tagged as building=yes instead of building=mosque"
        })

    # 8. Mapped as single node instead of building polygon
    if props.get("geom_type") == "Point":
        issues.append({
            "id": "mapped_as_node",
            "title_ar": "مرسوم كنقطة وليس كمساحة (مبنى) — يفضّل رسم حدود المبنى",
            "title_en": "Mapped as a single node instead of an area — ideally traced as a building outline"
        })

    # 9. ML spatial anomaly
    anom = props.get("ml_anomaly")
    if isinstance(anom, dict) and anom.get("is_anomaly"):
        diag = anom.get("diagnosis", "")
        diag_en = anom.get("diagnosis_en") or diag
        issues.append({
            "id": "ml_geometry_anomaly",
            "title_ar": f"🤖 شذوذ هندسي (ذكاء اصطناعي): {diag}",
            "title_en": f"🤖 ML Geometry Anomaly: {diag_en}"
        })

    # 10. Qibla misalignment
    if isinstance(anom, dict) and isinstance(anom.get("qibla_dev"), (int, float)):
        q_dev = anom["qibla_dev"]
        if q_dev >= qibla_threshold:
            issues.append({
                "id": "qibla_deviation",
                "title_ar": f"🕋 انحراف حاد عن القبلة ({q_dev}°)",
                "title_en": f"🕋 Severe Qibla deviation ({q_dev}°)"
            })

    # 11. Mapped twice
    if props.get("duplicate_poi"):
        issues.append({
            "id": "duplicate_poi",
            "title_ar": "مكرر: المبنى ونقطة داخله كلاهما موسوم كدار عبادة",
            "title_en": "Mapped twice: both building and point inside are tagged"
        })

    return issues


class DataService:
    def __init__(self):
        self.places: List[Dict[str, Any]] = []
        self.places_by_key: Dict[Tuple[str, int], Dict[str, Any]] = {}
        self.spatial_tree: Optional[STRtree] = None
        self.points_list: List[Point] = []
        self.gaps_data: Dict[str, Any] = {}
        self.gaps_list: List[Dict[str, Any]] = []
        self.suggestions: List[Dict[str, Any]] = []
        self.boundary_data: Optional[Dict[str, Any]] = None
        self.summary_data: Dict[str, Any] = {}
        self.is_loaded: bool = False
        self.load_error: Optional[str] = None

    def load(self):
        """Loads and indexes datasets."""
        try:
            # 1. Summary
            if os.path.exists(Config.SUMMARY_JSON):
                with open(Config.SUMMARY_JSON, "r", encoding="utf-8") as f:
                    self.summary_data = json.load(f)

            # 2. Sizes
            sizes = {}
            if os.path.exists(Config.MOSQUE_SIZES_JSON):
                with open(Config.MOSQUE_SIZES_JSON, "r", encoding="utf-8") as f:
                    sizes = json.load(f)

            # 3. Anomalies
            anomalies = {}
            if os.path.exists(Config.MOSQUE_ANOMALIES_JSON):
                with open(Config.MOSQUE_ANOMALIES_JSON, "r", encoding="utf-8") as f:
                    anomalies = json.load(f)

            # 4. Places
            if os.path.exists(Config.PLACES_GEOJSON):
                with open(Config.PLACES_GEOJSON, "r", encoding="utf-8") as f:
                    geojson = json.load(f)
                    features = geojson.get("features", [])

                pts = []
                self.places = []
                self.places_by_key = {}

                for idx, feat in enumerate(features):
                    props = feat.get("properties", {})
                    geom = feat.get("geometry", {})
                    coords = geom.get("coordinates")

                    if not coords or len(coords) < 2:
                        continue

                    lon, lat = coords[0], coords[1]
                    osm_id = props.get("osm_id")
                    osm_type = osm_type_of(props)
                    props["osm_type"] = osm_type

                    # Attach size
                    if props.get("geom_type") == "Polygon" and str(osm_id) in sizes:
                        props["size_area_m2"] = sizes[str(osm_id)].get("area_m2")

                    # Attach ML anomaly
                    if props.get("geom_type") == "Polygon" and str(osm_id) in anomalies:
                        props["ml_anomaly"] = anomalies[str(osm_id)]

                    # Precompute normalized names for search
                    name_ar = props.get("name_original") or props.get("name") or ""
                    name_en = props.get("name_en_original") or props.get("name_en") or ""
                    props["_norm_name"] = (normalize_arabic(name_ar) + " " + name_en.lower()).strip()

                    self.places.append(feat)
                    self.places_by_key[(osm_type, int(osm_id))] = feat
                    pts.append(Point(lon, lat))

                self.points_list = pts
                if pts:
                    self.spatial_tree = STRtree(pts)

            # 5. Gaps
            if os.path.exists(Config.GAPS_JSON):
                with open(Config.GAPS_JSON, "r", encoding="utf-8") as f:
                    self.gaps_data = json.load(f)
                    g = self.gaps_data.get("grid_size", 0.004)
                    raw_cells = self.gaps_data.get("cells", [])
                    self.gaps_list = [
                        {
                            "gx": c[0],
                            "gy": c[1],
                            "lon": round((c[0] + 0.5) * g, 6),
                            "lat": round((c[1] + 0.5) * g, 6),
                            "road_length_m": c[2],
                            "gap_score": c[3],
                        }
                        for c in raw_cells
                    ]

            # 6. Suggestions
            if os.path.exists(Config.SUGGESTED_MOSQUES_GEOJSON):
                with open(Config.SUGGESTED_MOSQUES_GEOJSON, "r", encoding="utf-8") as f:
                    sug_geojson = json.load(f)
                    self.suggestions = sug_geojson.get("features", [])

            # 7. Boundary
            if os.path.exists(Config.SA_BOUNDARY_GEOJSON):
                with open(Config.SA_BOUNDARY_GEOJSON, "r", encoding="utf-8") as f:
                    self.boundary_data = json.load(f)

            self.is_loaded = True
            self.load_error = None
        except Exception as e:
            self.is_loaded = False
            self.load_error = str(e)
            raise

    def query_places(
        self,
        bbox: Optional[Tuple[float, float, float, float]] = None,
        q: Optional[str] = None,
        religion: Optional[str] = None,
        issue: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        min_size_m2: float = 20.0,
        max_size_m2: float = 15000.0,
        qibla_threshold: float = 20.0,
    ) -> Dict[str, Any]:
        """Queries places with spatial bbox, full-text search, and quality filters."""
        if not self.is_loaded:
            self.load()

        # Spatial filter candidate indices
        candidate_indices = None
        if bbox and self.spatial_tree and len(self.points_list) > 0:
            minx, miny, maxx, maxy = bbox
            search_box = box(minx, miny, maxx, maxy)
            candidate_indices = set(self.spatial_tree.query(search_box))

        norm_q = normalize_arabic(q.strip()) if q and q.strip() else None

        filtered = []
        indices_to_check = range(len(self.places)) if candidate_indices is None else candidate_indices

        for idx in indices_to_check:
            feat = self.places[idx]
            props = feat.get("properties", {})

            # Religion filter
            if religion and religion != "all":
                if props.get("religion") != religion:
                    continue

            # Text query
            if norm_q:
                norm_name = props.get("_norm_name", "")
                if norm_q not in norm_name and norm_q not in str(props.get("osm_id", "")):
                    continue

            # Issue filter
            if issue and issue != "all":
                issues = get_quality_issues(props, min_size_m2, max_size_m2, qibla_threshold)
                if not any(iss["id"] == issue for iss in issues):
                    continue

            filtered.append(feat)

        total = len(filtered)
        paginated = filtered[offset : offset + limit] if limit > 0 else filtered

        return {
            "total": total,
            "count": len(paginated),
            "limit": limit,
            "offset": offset,
            "features": paginated,
        }

    def get_place(self, osm_type: str, osm_id: int) -> Optional[Dict[str, Any]]:
        """Retrieves a single place of worship with full details and issues."""
        if not self.is_loaded:
            self.load()
        feat = self.places_by_key.get((osm_type.lower(), int(osm_id)))
        if not feat:
            return None
        # Copy and append detected issues
        res = json.loads(json.dumps(feat))
        props = res.setdefault("properties", {})
        props["issues"] = get_quality_issues(props)
        return res

    def query_nearby(self, lat: float, lon: float, radius_km: float = 5.0, limit: int = 50) -> List[Dict[str, Any]]:
        """Finds places within radius_km of (lat, lon)."""
        if not self.is_loaded:
            self.load()

        deg_lat = radius_km / 110.574
        deg_lon = radius_km / (111.320 * math.cos(math.radians(lat)))
        minx, miny = lon - deg_lon, lat - deg_lat
        maxx, maxy = lon + deg_lon, lat + deg_lat

        cand_indices = self.spatial_tree.query(box(minx, miny, maxx, maxy))
        results = []

        ref_rad = math.radians(lat)
        m_lat = 110574.0
        m_lon = 111320.0 * math.cos(ref_rad)

        for idx in cand_indices:
            feat = self.places[idx]
            c = feat["geometry"]["coordinates"]
            dx = (c[0] - lon) * m_lon
            dy = (c[1] - lat) * m_lat
            dist_m = math.hypot(dx, dy)
            if dist_m <= radius_km * 1000.0:
                item = dict(feat)
                item["distance_m"] = round(dist_m, 1)
                results.append(item)

        results.sort(key=lambda x: x["distance_m"])
        return results[:limit]

    def query_gaps(
        self,
        bbox: Optional[Tuple[float, float, float, float]] = None,
        min_score: float = 0.0,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Queries coverage gap cells."""
        if not self.is_loaded:
            self.load()

        res = []
        for cell in self.gaps_list:
            if cell["gap_score"] < min_score:
                continue
            if bbox:
                minx, miny, maxx, maxy = bbox
                if not (minx <= cell["lon"] <= maxx and miny <= cell["lat"] <= maxy):
                    continue
            res.append(cell)
            if limit > 0 and len(res) >= limit:
                break
        return res

    def query_suggestions(
        self,
        bbox: Optional[Tuple[float, float, float, float]] = None,
        q: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Queries Wikidata suggestions."""
        if not self.is_loaded:
            self.load()

        norm_q = normalize_arabic(q.strip()) if q and q.strip() else None
        res = []

        for feat in self.suggestions:
            c = feat.get("geometry", {}).get("coordinates", [])
            if len(c) < 2:
                continue
            lon, lat = c[0], c[1]

            if bbox:
                minx, miny, maxx, maxy = bbox
                if not (minx <= lon <= maxx and miny <= lat <= maxy):
                    continue

            if norm_q:
                name_ar = feat.get("properties", {}).get("name") or ""
                name_en = feat.get("properties", {}).get("name:en") or ""
                norm_full = normalize_arabic(name_ar) + " " + name_en.lower()
                if norm_q not in norm_full:
                    continue

            res.append(feat)
            if limit > 0 and len(res) >= limit:
                break

        return res


# Global singleton
_data_service = DataService()


def get_data_service() -> DataService:
    global _data_service
    if not _data_service.is_loaded:
        _data_service.load()
    return _data_service
