#!/usr/bin/env python3
"""
Ingests Manara's processed datasets into PostGIS.

Runs inside the pipeline container after validation. When DATABASE_URL
(or MANARA_DATABASE_URL) is set, it populates staging tables, assigns regions
spatially with ST_Within, and swaps tables into production in a single atomic
transaction. If DATABASE_URL is not set, it exits cleanly with code 0.
"""

import json
import os
import sys
import time

from common import BASE_DIR, configure_utf8_output, normalize_arabic, read_summary

configure_utf8_output()

DATABASE_URL = os.environ.get("MANARA_DATABASE_URL") or os.environ.get("DATABASE_URL")


def get_connection(db_url):
    try:
        import psycopg
        return psycopg.connect(db_url, autocommit=True)
    except ImportError:
        sys.exit("psycopg is not installed. Install with: pip install 'psycopg[binary]'")
    except Exception as e:
        sys.exit(f"Could not connect to database: {e}")


def init_db(conn):
    """Ensure PostGIS and pg_trgm extensions and production schema exist."""
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

        cur.execute("""
        CREATE TABLE IF NOT EXISTS regions (
            code VARCHAR(10) PRIMARY KEY,
            osm_id BIGINT NOT NULL,
            name VARCHAR(255) NOT NULL,
            name_en VARCHAR(255) NOT NULL,
            geom GEOMETRY(Geometry, 4326) NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_regions_geom ON regions USING GIST (geom);

        CREATE TABLE IF NOT EXISTS places (
            id INT PRIMARY KEY,
            osm_type VARCHAR(16) NOT NULL,
            osm_id BIGINT NOT NULL,
            version INT,
            edited_at TIMESTAMPTZ,
            name TEXT DEFAULT '',
            name_norm TEXT DEFAULT '',
            name_en TEXT DEFAULT '',
            religion VARCHAR(64) DEFAULT 'unknown',
            denomination VARCHAR(64) DEFAULT 'unknown',
            building VARCHAR(64) DEFAULT '',
            amenity VARCHAR(64) DEFAULT '',
            poi_node_id BIGINT,
            tags JSONB DEFAULT '{}'::jsonb,
            geom_type VARCHAR(32) NOT NULL,
            geom GEOMETRY(Point, 4326) NOT NULL,
            area_m2 DOUBLE PRECISION,
            anomaly_score DOUBLE PRECISION,
            qibla_dev DOUBLE PRECISION,
            region_code VARCHAR(10),
            dataset_id VARCHAR(64)
        );
        CREATE INDEX IF NOT EXISTS idx_places_osm ON places (osm_type, osm_id);
        CREATE INDEX IF NOT EXISTS idx_places_geom ON places USING GIST (geom);
        CREATE INDEX IF NOT EXISTS idx_places_name_norm_trgm ON places USING GIN (name_norm gin_trgm_ops);
        CREATE INDEX IF NOT EXISTS idx_places_region ON places (region_code);
        CREATE INDEX IF NOT EXISTS idx_places_religion ON places (religion);

        CREATE TABLE IF NOT EXISTS gaps (
            id INT PRIMARY KEY,
            grid_x INT NOT NULL,
            grid_y INT NOT NULL,
            road_length_m DOUBLE PRECISION NOT NULL,
            gap_score DOUBLE PRECISION NOT NULL,
            urgency_score DOUBLE PRECISION DEFAULT 0.0,
            geom GEOMETRY(Point, 4326) NOT NULL,
            region_code VARCHAR(10)
        );
        ALTER TABLE gaps ADD COLUMN IF NOT EXISTS urgency_score DOUBLE PRECISION DEFAULT 0.0;
        CREATE INDEX IF NOT EXISTS idx_gaps_geom ON gaps USING GIST (geom);
        CREATE INDEX IF NOT EXISTS idx_gaps_region ON gaps (region_code);

        CREATE TABLE IF NOT EXISTS suggestions (
            id INT PRIMARY KEY,
            wikidata_id VARCHAR(32) NOT NULL,
            name TEXT DEFAULT '',
            name_norm TEXT DEFAULT '',
            name_en TEXT DEFAULT '',
            nearest_osm_m INT,
            is_unnamed BOOLEAN DEFAULT FALSE,
            geom GEOMETRY(Point, 4326) NOT NULL,
            region_code VARCHAR(10)
        );
        ALTER TABLE suggestions ADD COLUMN IF NOT EXISTS nearest_osm_m INT;
        ALTER TABLE suggestions ADD COLUMN IF NOT EXISTS is_unnamed BOOLEAN DEFAULT FALSE;
        CREATE INDEX IF NOT EXISTS idx_suggestions_wikidata ON suggestions (wikidata_id);
        CREATE INDEX IF NOT EXISTS idx_suggestions_geom ON suggestions USING GIST (geom);
        CREATE INDEX IF NOT EXISTS idx_suggestions_name_norm_trgm ON suggestions USING GIN (name_norm gin_trgm_ops);
        CREATE INDEX IF NOT EXISTS idx_suggestions_region ON suggestions (region_code);

        CREATE TABLE IF NOT EXISTS dataset_versions (
            version VARCHAR(64) PRIMARY KEY,
            pbf_date DATE,
            published_at TIMESTAMPTZ NOT NULL,
            metadata JSONB NOT NULL
        );

        CREATE TABLE IF NOT EXISTS region_stats_history (
            id SERIAL PRIMARY KEY,
            version VARCHAR(64),
            region_code VARCHAR(10),
            places_count INT NOT NULL DEFAULT 0,
            gaps_count INT NOT NULL DEFAULT 0,
            suggestions_count INT NOT NULL DEFAULT 0,
            anomalies_count INT NOT NULL DEFAULT 0,
            recorded_at TIMESTAMPTZ NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_stats_history_ver_region
            ON region_stats_history (version, region_code);

        CREATE TABLE IF NOT EXISTS issues (
            rule_id VARCHAR(64) NOT NULL,
            osm_type VARCHAR(16) NOT NULL,
            osm_id BIGINT NOT NULL,
            severity VARCHAR(16) NOT NULL DEFAULT 'medium',
            region_code VARCHAR(10),
            suggested_fix JSONB,
            PRIMARY KEY (rule_id, osm_type, osm_id)
        );
        CREATE INDEX IF NOT EXISTS idx_issues_rule ON issues (rule_id);
        CREATE INDEX IF NOT EXISTS idx_issues_region ON issues (region_code);
        CREATE INDEX IF NOT EXISTS idx_issues_osm ON issues (osm_type, osm_id);
        """)


def load_staging_data(conn, data_dir=BASE_DIR):
    """Loads all datasets into clean staging tables."""
    summary = read_summary()
    version = "v" + summary.get("updated_at", "").replace("-", "").replace(":", "")

    regions_file = os.path.join(data_dir, "sa_regions.geojson")
    places_file = os.path.join(data_dir, "places_of_worship_sa.geojson")
    gaps_file = os.path.join(data_dir, "worship_gaps_sa.json")
    sizes_file = os.path.join(data_dir, "mosque_sizes.json")
    anomalies_file = os.path.join(data_dir, "mosque_anomalies.json")
    suggestions_file = os.path.join(data_dir, "suggested_mosques_sa.geojson")

    # 1. Staging tables setup
    with conn.cursor() as cur:
        cur.execute("""
        DROP TABLE IF EXISTS places_staging CASCADE;
        DROP TABLE IF EXISTS gaps_staging CASCADE;
        DROP TABLE IF EXISTS suggestions_staging CASCADE;
        DROP TABLE IF EXISTS regions_staging CASCADE;

        DROP TABLE IF EXISTS issues_staging CASCADE;
        CREATE TABLE regions_staging (LIKE regions INCLUDING ALL);
        CREATE TABLE places_staging (LIKE places INCLUDING ALL);
        CREATE TABLE gaps_staging (LIKE gaps INCLUDING ALL);
        CREATE TABLE suggestions_staging (LIKE suggestions INCLUDING ALL);
        CREATE TABLE issues_staging (LIKE issues INCLUDING ALL);
        """)

    # 2. Ingest Regions
    if os.path.exists(regions_file):
        with open(regions_file, "r", encoding="utf-8") as f:
            regions_data = json.load(f)
        with conn.cursor() as cur:
            for feat in regions_data.get("features", []):
                p = feat.get("properties", {})
                geom_json = json.dumps(feat.get("geometry", {}))
                cur.execute("""
                INSERT INTO regions_staging (code, osm_id, name, name_en, geom)
                VALUES (%s, %s, %s, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326));
                """, (p.get("code"), p.get("osm_id"), p.get("name"), p.get("name_en"), geom_json))
        print(f"  [OK] Ingested {len(regions_data.get('features', []))} provinces into regions_staging.")

    # 3. Ingest Places
    sizes = {}
    if os.path.exists(sizes_file):
        with open(sizes_file, "r", encoding="utf-8") as f:
            sizes = {int(k): v for k, v in json.load(f).items()}

    anomalies = {}
    if os.path.exists(anomalies_file):
        with open(anomalies_file, "r", encoding="utf-8") as f:
            anom_data = json.load(f)
            anomalies = anom_data.get("outliers", {}) or anom_data

    if os.path.exists(places_file):
        with open(places_file, "r", encoding="utf-8") as f:
            places_data = json.load(f)

        places_rows = []
        for idx, feat in enumerate(places_data.get("features", []), start=1):
            p = feat.get("properties", {})
            geom = feat.get("geometry", {})
            coords = geom.get("coordinates", [0, 0])
            osm_id = p.get("osm_id")
            name = p.get("name", "")
            name_norm = normalize_arabic(name) if name else ""

            size_val = sizes.get(osm_id) or sizes.get(str(osm_id))
            if isinstance(size_val, dict):
                area_m2 = size_val.get("area_m2")
            elif isinstance(size_val, (int, float)):
                area_m2 = float(size_val)
            else:
                area_m2 = None

            anom_info = anomalies.get(str(osm_id)) or anomalies.get(osm_id) or {}
            anom_score = anom_info.get("anomaly_score") if isinstance(anom_info, dict) else None
            qibla_dev = (anom_info.get("qibla_dev") or anom_info.get("qibla_deviation")) if isinstance(anom_info, dict) else None

            geom_type = p.get("geom_type", "Point")
            osm_type = {"Point": "node", "Polygon": "way", "Relation": "relation"}.get(geom_type, geom_type.lower())

            places_rows.append((
                idx,
                osm_type,
                osm_id,
                p.get("version"),
                p.get("edited_at"),
                name,
                name_norm,
                p.get("name_en", ""),
                p.get("religion", "unknown"),
                p.get("denomination", "unknown"),
                p.get("building", ""),
                p.get("amenity", ""),
                p.get("poi_node_id"),
                json.dumps(p),
                geom_type,
                coords[0],
                coords[1],
                area_m2,
                anom_score,
                qibla_dev,
                version,
            ))

        with conn.cursor() as cur:
            with cur.copy("""
            COPY places_staging (
                id, osm_type, osm_id, version, edited_at, name, name_norm, name_en,
                religion, denomination, building, amenity, poi_node_id, tags,
                geom_type, geom, area_m2, anomaly_score, qibla_dev, dataset_id
            ) FROM STDIN
            """) as copy:
                for r in places_rows:
                    geom_wkt = f"SRID=4326;POINT({r[15]} {r[16]})"
                    copy.write_row((
                        r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7],
                        r[8], r[9], r[10], r[11], r[12], r[13],
                        r[14], geom_wkt, r[17], r[18], r[19], r[20]
                    ))
        print(f"  [OK] Ingested {len(places_rows)} places into places_staging.")

    # 4. Ingest Gaps
    if os.path.exists(gaps_file):
        with open(gaps_file, "r", encoding="utf-8") as f:
            gaps_data = json.load(f)
        grid_size = gaps_data.get("grid_size", 0.004)
        gaps_rows = []
        for idx, cell in enumerate(gaps_data.get("cells", []), start=1):
            gx, gy, road_len, gap_score = cell[0], cell[1], cell[2], cell[3]
            urgency_score = cell[4] if len(cell) > 4 else round(gap_score, 1)
            lon = round(gx * grid_size, 6)
            lat = round(gy * grid_size, 6)
            gaps_rows.append((idx, gx, gy, road_len, gap_score, urgency_score, lon, lat))

        with conn.cursor() as cur:
            with cur.copy("""
            COPY gaps_staging (id, grid_x, grid_y, road_length_m, gap_score, urgency_score, geom) FROM STDIN
            """) as copy:
                for r in gaps_rows:
                    geom_wkt = f"SRID=4326;POINT({r[6]} {r[7]})"
                    copy.write_row((r[0], r[1], r[2], r[3], r[4], r[5], geom_wkt))
        print(f"  [OK] Ingested {len(gaps_rows)} gaps into gaps_staging.")

    # 5. Ingest Suggestions
    if os.path.exists(suggestions_file):
        with open(suggestions_file, "r", encoding="utf-8") as f:
            sug_data = json.load(f)
        sug_rows = []
        for idx, feat in enumerate(sug_data.get("features", []), start=1):
            p = feat.get("properties", {})
            coords = feat.get("geometry", {}).get("coordinates", [0, 0])
            name = p.get("name") or p.get("name_ar", "")
            name_norm = normalize_arabic(name) if name else ""
            wikidata_id = p.get("qid") or p.get("wikidata_id") or p.get("id", "")
            sug_rows.append((
                idx,
                wikidata_id,
                name,
                name_norm,
                p.get("name_en", ""),
                p.get("nearest_osm_m"),
                bool(p.get("is_unnamed", False)),
                coords[0],
                coords[1],
            ))

        with conn.cursor() as cur:
            with cur.copy("""
            COPY suggestions_staging (id, wikidata_id, name, name_norm, name_en, nearest_osm_m, is_unnamed, geom) FROM STDIN
            """) as copy:
                for r in sug_rows:
                    geom_wkt = f"SRID=4326;POINT({r[7]} {r[8]})"
                    copy.write_row((r[0], r[1], r[2], r[3], r[4], r[5], r[6], geom_wkt))
        print(f"  [OK] Ingested {len(sug_rows)} suggestions into suggestions_staging.")

    # 6. Spatial Assignment (ST_Within)
    print("  Assigning provinces spatially with ST_Within...")
    with conn.cursor() as cur:
        cur.execute("""
        UPDATE places_staging p
        SET region_code = r.code
        FROM regions_staging r
        WHERE ST_Within(p.geom, r.geom);

        UPDATE gaps_staging g
        SET region_code = r.code
        FROM regions_staging r
        WHERE ST_Within(g.geom, r.geom);

        UPDATE suggestions_staging s
        SET region_code = r.code
        FROM regions_staging r
        WHERE ST_Within(s.geom, r.geom);
        """)
    print("  [OK] Spatial province assignment complete.")

    # 6b. Populate QA Issues from places_staging
    print("  Populating QA issues from places_staging...")
    with conn.cursor() as cur:
        cur.execute("""
        INSERT INTO issues_staging (rule_id, osm_type, osm_id, severity, region_code, suggested_fix)
        SELECT 'missing_amenity', osm_type, osm_id, 'high', region_code, '{"amenity": "place_of_worship"}'::jsonb
        FROM places_staging WHERE building = 'mosque' AND amenity != 'place_of_worship'
        ON CONFLICT DO NOTHING;

        INSERT INTO issues_staging (rule_id, osm_type, osm_id, severity, region_code, suggested_fix)
        SELECT 'missing_name', osm_type, osm_id, 'medium', region_code, NULL
        FROM places_staging WHERE name = '' OR name_norm IN ('مسجد', 'جامع', 'مصلى')
        ON CONFLICT DO NOTHING;

        INSERT INTO issues_staging (rule_id, osm_type, osm_id, severity, region_code, suggested_fix)
        SELECT 'missing_name_en', osm_type, osm_id, 'medium', region_code, NULL
        FROM places_staging WHERE name != '' AND name_norm NOT IN ('مسجد', 'جامع', 'مصلى') AND (name_en = '' OR name = name_en)
        ON CONFLICT DO NOTHING;

        INSERT INTO issues_staging (rule_id, osm_type, osm_id, severity, region_code, suggested_fix)
        SELECT 'missing_denom', osm_type, osm_id, 'medium', region_code, NULL
        FROM places_staging WHERE religion = 'muslim' AND (denomination IS NULL OR denomination = '' OR denomination = 'unknown')
        ON CONFLICT DO NOTHING;

        INSERT INTO issues_staging (rule_id, osm_type, osm_id, severity, region_code, suggested_fix)
        SELECT 'building_yes', osm_type, osm_id, 'medium', region_code, '{"building": "mosque"}'::jsonb
        FROM places_staging WHERE amenity = 'place_of_worship' AND building = 'yes'
        ON CONFLICT DO NOTHING;

        INSERT INTO issues_staging (rule_id, osm_type, osm_id, severity, region_code, suggested_fix)
        SELECT 'size_too_small', osm_type, osm_id, 'low', region_code, NULL
        FROM places_staging WHERE area_m2 IS NOT NULL AND area_m2 < 30.0
        ON CONFLICT DO NOTHING;

        INSERT INTO issues_staging (rule_id, osm_type, osm_id, severity, region_code, suggested_fix)
        SELECT 'size_too_large', osm_type, osm_id, 'low', region_code, NULL
        FROM places_staging WHERE area_m2 IS NOT NULL AND area_m2 > 10000.0
        ON CONFLICT DO NOTHING;

        INSERT INTO issues_staging (rule_id, osm_type, osm_id, severity, region_code, suggested_fix)
        SELECT 'ml_geometry_anomaly', osm_type, osm_id, 'high', region_code, NULL
        FROM places_staging WHERE anomaly_score IS NOT NULL AND anomaly_score < -0.3
        ON CONFLICT DO NOTHING;

        INSERT INTO issues_staging (rule_id, osm_type, osm_id, severity, region_code, suggested_fix)
        SELECT 'qibla_deviation', osm_type, osm_id, 'high', region_code, NULL
        FROM places_staging WHERE qibla_dev IS NOT NULL AND qibla_dev >= 20.0
        ON CONFLICT DO NOTHING;
        """)
    print("  [OK] QA issues populated into issues_staging.")

    # 7. Record History Stats and Dataset Version
    now_ts = summary.get("updated_at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    pbf_date = summary.get("pbf_date")
    with conn.cursor() as cur:
        cur.execute("""
        INSERT INTO dataset_versions (version, pbf_date, published_at, metadata)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (version) DO UPDATE SET metadata = EXCLUDED.metadata;
        """, (version, pbf_date, now_ts, json.dumps(summary)))

        cur.execute("""
        WITH place_counts AS (
            SELECT region_code,
                   COUNT(*) AS places_count,
                   COUNT(*) FILTER (WHERE anomaly_score < 0) AS anomalies_count
            FROM places_staging
            WHERE region_code IS NOT NULL
            GROUP BY region_code
        ),
        gap_counts AS (
            SELECT region_code, COUNT(*) AS gaps_count
            FROM gaps_staging
            WHERE region_code IS NOT NULL
            GROUP BY region_code
        ),
        sug_counts AS (
            SELECT region_code, COUNT(*) AS suggestions_count
            FROM suggestions_staging
            WHERE region_code IS NOT NULL
            GROUP BY region_code
        )
        INSERT INTO region_stats_history (
            version, region_code, places_count, gaps_count, suggestions_count, anomalies_count, recorded_at
        )
        SELECT
            %s AS version,
            r.code AS region_code,
            COALESCE(p.places_count, 0),
            COALESCE(g.gaps_count, 0),
            COALESCE(s.suggestions_count, 0),
            COALESCE(p.anomalies_count, 0),
            %s::timestamptz AS recorded_at
        FROM regions_staging r
        LEFT JOIN place_counts p ON p.region_code = r.code
        LEFT JOIN gap_counts g ON g.region_code = r.code
        LEFT JOIN sug_counts s ON s.region_code = r.code
        ON CONFLICT (version, region_code) DO NOTHING;
        """, (version, now_ts))
        print(f"  [OK] Regional history stats recorded for version {version}.")


def swap_staging_to_production(conn):
    """Atomically swaps staging tables into production in a single transaction."""
    print("Performing atomic table swap to production...")
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("""
            DROP TABLE IF EXISTS places_old CASCADE;
            DROP TABLE IF EXISTS gaps_old CASCADE;
            DROP TABLE IF EXISTS suggestions_old CASCADE;
            DROP TABLE IF EXISTS regions_old CASCADE;
            DROP TABLE IF EXISTS issues_old CASCADE;

            ALTER TABLE IF EXISTS places RENAME TO places_old;
            ALTER TABLE places_staging RENAME TO places;

            ALTER TABLE IF EXISTS gaps RENAME TO gaps_old;
            ALTER TABLE gaps_staging RENAME TO gaps;

            ALTER TABLE IF EXISTS suggestions RENAME TO suggestions_old;
            ALTER TABLE suggestions_staging RENAME TO suggestions;

            ALTER TABLE IF EXISTS regions RENAME TO regions_old;
            ALTER TABLE regions_staging RENAME TO regions;

            ALTER TABLE IF EXISTS issues RENAME TO issues_old;
            ALTER TABLE issues_staging RENAME TO issues;

            DROP TABLE IF EXISTS places_old CASCADE;
            DROP TABLE IF EXISTS gaps_old CASCADE;
            DROP TABLE IF EXISTS suggestions_old CASCADE;
            DROP TABLE IF EXISTS regions_old CASCADE;
            DROP TABLE IF EXISTS issues_old CASCADE;
            """)
    print("  [SUCCESS] All tables swapped to production atomically!")



def update_sprint_workloads(conn):
    """
    Computes and updates tile workloads and pending_refresh for active/draft sprints.
    Workload = count of issues matching sprint rules + count of gaps exceeding min urgency within tile bbox.
    pending_refresh = TRUE if verified edits exist newer than published_at for places within the tile.
    """
    print("Updating active sprint tile workloads and pending refresh flags...")
    with conn.cursor() as cur:
        # Check if sprints table exists
        cur.execute("SELECT to_regclass('public.sprints');")
        res = cur.fetchone()
        if not res or not res[0]:
            print("  [SKIP] sprints table does not exist.")
            return

        cur.execute("""
            SELECT id, slug, rule_ids, gap_min_urgency
            FROM sprints
            WHERE status IN ('draft', 'active');
        """)
        active_sprints = cur.fetchall()
        if not active_sprints:
            print("  [SKIP] No active or draft sprints found.")
            return

        # Fetch latest dataset published_at timestamp
        cur.execute("""
            SELECT published_at FROM dataset_versions
            ORDER BY published_at DESC LIMIT 1;
        """)
        row = cur.fetchone()
        latest_published = row[0] if row else None

        for sprint_id, slug, rule_ids, gap_min_urgency in active_sprints:
            # 1. Update workload per tile
            cur.execute("""
                WITH tile_boxes AS (
                    SELECT
                        st.tile_id,
                        ST_MakeEnvelope(st.bbox[1]::double precision, st.bbox[2]::double precision,
                                        st.bbox[3]::double precision, st.bbox[4]::double precision, 4326) AS envelope
                    FROM sprint_tiles st
                    WHERE st.sprint_id = %s
                ),
                tile_issues AS (
                    SELECT
                        tb.tile_id,
                        COUNT(i.rule_id) AS issue_count
                    FROM tile_boxes tb
                    JOIN places p ON ST_Within(p.geom, tb.envelope)
                    JOIN issues i ON i.osm_type = p.osm_type AND i.osm_id = p.osm_id
                    WHERE (%s::text[] IS NULL OR cardinality(%s::text[]) = 0 OR i.rule_id = ANY(%s::text[]))
                    GROUP BY tb.tile_id
                ),
                tile_gaps AS (
                    SELECT
                        tb.tile_id,
                        COUNT(g.id) AS gap_count
                    FROM tile_boxes tb
                    JOIN gaps g ON ST_Within(g.geom, tb.envelope)
                    WHERE (%s::int IS NULL OR g.urgency_score >= %s::int)
                    GROUP BY tb.tile_id
                )
                UPDATE sprint_tiles st
                SET workload = COALESCE(ti.issue_count, 0) + COALESCE(tg.gap_count, 0)
                FROM tile_boxes tb
                LEFT JOIN tile_issues ti ON tb.tile_id = ti.tile_id
                LEFT JOIN tile_gaps tg ON tb.tile_id = tg.tile_id
                WHERE st.sprint_id = %s
                  AND st.tile_id = tb.tile_id;
            """, (sprint_id, rule_ids, rule_ids, rule_ids, gap_min_urgency, gap_min_urgency, sprint_id))

            # 2. Update pending_refresh based on verified edits newer than published_at
            if not latest_published:
                cur.execute("UPDATE sprint_tiles SET pending_refresh = FALSE WHERE sprint_id = %s;", (sprint_id,))
            else:
                cur.execute("""
                    WITH recent_edits AS (
                        SELECT jsonb_array_elements(objects) AS obj
                        FROM edits
                        WHERE created_at > %s
                    ),
                    edited_places AS (
                        SELECT p.geom
                        FROM recent_edits re
                        JOIN places p ON p.osm_type = (re.obj->>'type') AND p.osm_id = (re.obj->>'id')::bigint
                    ),
                    refreshed_tiles AS (
                        SELECT DISTINCT st.tile_id
                        FROM sprint_tiles st
                        JOIN edited_places ep ON ST_Within(
                            ep.geom,
                            ST_MakeEnvelope(st.bbox[1]::double precision, st.bbox[2]::double precision,
                                            st.bbox[3]::double precision, st.bbox[4]::double precision, 4326)
                        )
                        WHERE st.sprint_id = %s
                    )
                    UPDATE sprint_tiles st
                    SET pending_refresh = (rt.tile_id IS NOT NULL)
                    FROM sprint_tiles st2
                    LEFT JOIN refreshed_tiles rt ON st2.tile_id = rt.tile_id AND st2.sprint_id = %s
                    WHERE st.sprint_id = %s
                      AND st.tile_id = st2.tile_id;
                """, (latest_published, sprint_id, sprint_id, sprint_id))

            print(f"  [OK] Updated workloads and refresh status for sprint '{slug}' (ID {sprint_id}).")


def main():
    if not DATABASE_URL:
        print("[SKIP] No DATABASE_URL set; database loading skipped.")
        return

    started = time.time()
    print(f"Connecting to PostGIS...")
    conn = get_connection(DATABASE_URL)
    try:
        init_db(conn)
        load_staging_data(conn)
        swap_staging_to_production(conn)
        update_sprint_workloads(conn)
        print(f"Database loading finished successfully in {time.time() - started:.1f}s.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
