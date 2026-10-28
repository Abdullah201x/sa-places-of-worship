import os
from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.database import get_db

router = APIRouter(tags=["seo"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

GENERIC_NAMES = {"مسجد", "الجامع", "جامع", "المسجد", "مصلى", "المصلى", "mosque", "masjid"}


def is_named_place(name: str | None) -> bool:
    if not name:
        return False
    cleaned = name.strip().lower()
    return cleaned != "" and cleaned not in GENERIC_NAMES


@router.get("/region/{code}", response_class=HTMLResponse)
def get_region_page(
    request: Request,
    code: str = Path(..., pattern="^SA-\\d{2}$"),
    conn=Depends(get_db),
):
    """Rich SSR landing page for a Saudi administrative province."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT code, name, name_en,
                   ST_Y(ST_Centroid(geom)) AS center_lat,
                   ST_X(ST_Centroid(geom)) AS center_lon
            FROM regions
            WHERE code = %s;
        """, (code.upper(),))
        region = cur.fetchone()
        if not region:
            raise HTTPException(status_code=404, detail=f"Region {code} not found.")

        # Region stats
        cur.execute("""
            SELECT
                (SELECT COUNT(*) FROM places WHERE region_code = %s) AS places_count,
                (SELECT COUNT(*) FROM gaps WHERE region_code = %s) AS gaps_count,
                (SELECT COUNT(*) FROM suggestions WHERE region_code = %s) AS suggestions_count,
                (SELECT COUNT(*) FROM places WHERE region_code = %s AND anomaly_score < 0) AS anomalies_count,
                (SELECT COUNT(*) FROM places WHERE region_code = %s AND qibla_dev >= 20.0) AS qibla_deviated_count;
        """, (code.upper(), code.upper(), code.upper(), code.upper(), code.upper()))
        stats_row = dict(cur.fetchone())

        places = stats_row["places_count"]
        suggestions = stats_row["suggestions_count"]
        denom = places + suggestions
        stats_row["coverage_pct"] = (places / denom * 100) if denom > 0 else 0

        # Sample of named places in this region
        cur.execute("""
            SELECT osm_type, osm_id, name, name_en, religion, denomination
            FROM places
            WHERE region_code = %s AND name != '' AND name IS NOT NULL
            ORDER BY area_m2 DESC NULLS LAST, osm_id ASC
            LIMIT 25;
        """, (code.upper(),))
        top_places = [dict(r) for r in cur.fetchall()]

    canonical_url = f"https://manara.saudiosm.org/region/{region['code']}"

    return templates.TemplateResponse(
        request=request,
        name="region.html",
        context={
            "region": dict(region),
            "stats": stats_row,
            "top_places": top_places,
            "center_lat": round(region["center_lat"] or 24.5, 4),
            "center_lon": round(region["center_lon"] or 45.0, 4),
            "canonical_url": canonical_url,
            "indexable": True,
        },
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/place/{osm_type}/{osm_id}", response_class=HTMLResponse)
def get_place_page(
    request: Request,
    osm_type: str = Path(..., pattern="^(node|way|relation)$"),
    osm_id: int = Path(..., gt=0),
    conn=Depends(get_db),
):
    """
    Rich SSR page for an individual place of worship.
    Named places are indexed by search engines; generic or unnamed places get noindex.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                p.osm_type,
                p.osm_id,
                p.version,
                p.name,
                p.name_en,
                p.religion,
                p.denomination,
                p.area_m2,
                p.qibla_dev,
                p.region_code,
                r.name AS region_name,
                ST_Y(p.geom) AS lat,
                ST_X(p.geom) AS lon
            FROM places p
            LEFT JOIN regions r ON r.code = p.region_code
            WHERE p.osm_type = %s AND p.osm_id = %s;
        """, (osm_type, osm_id))
        row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"Place {osm_type}/{osm_id} not found.")

        place = dict(row)

    canonical_url = f"https://manara.saudiosm.org/place/{place['osm_type']}/{place['osm_id']}"
    indexable = is_named_place(place.get("name"))

    return templates.TemplateResponse(
        request=request,
        name="place.html",
        context={
            "place": place,
            "region_name": place.get("region_name") or "",
            "lat": place.get("lat") or 0.0,
            "lon": place.get("lon") or 0.0,
            "canonical_url": canonical_url,
            "indexable": indexable,
        },
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/sitemap.xml")
def get_sitemap(conn=Depends(get_db)):
    """XML sitemap containing main pages, all 13 regions, and all named places."""
    base_url = "https://manara.saudiosm.org"

    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        f'  <url><loc>{base_url}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>',
        f'  <url><loc>{base_url}/community</loc><changefreq>daily</changefreq><priority>0.9</priority></url>',
        f'  <url><loc>{base_url}/about</loc><changefreq>monthly</changefreq><priority>0.5</priority></url>',
        f'  <url><loc>{base_url}/privacy</loc><changefreq>monthly</changefreq><priority>0.3</priority></url>',
    ]

    with conn.cursor() as cur:
        # All regions
        cur.execute("SELECT code FROM regions ORDER BY code ASC;")
        for r in cur.fetchall():
            xml_lines.append(
                f'  <url><loc>{base_url}/region/{r["code"]}</loc><changefreq>daily</changefreq><priority>0.8</priority></url>'
            )

        # Named places only
        cur.execute("""
            SELECT osm_type, osm_id, edited_at
            FROM places
            WHERE name != '' AND name IS NOT NULL
            ORDER BY osm_id ASC;
        """)
        for p in cur.fetchall():
            lastmod = ""
            if p.get("edited_at"):
                lastmod = f"<lastmod>{p['edited_at'].strftime('%Y-%m-%d')}</lastmod>"
            xml_lines.append(
                f'  <url><loc>{base_url}/place/{p["osm_type"]}/{p["osm_id"]}</loc>{lastmod}<changefreq>weekly</changefreq><priority>0.7</priority></url>'
            )

    xml_lines.append('</urlset>')

    return Response(
        content="\n".join(xml_lines),
        media_type="application/xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )
