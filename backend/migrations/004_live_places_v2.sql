-- 004_live_places_v2.sql
-- Live places v2: OSM timestamp, tombstones, source, changeset, plus the single
-- write path (manara_upsert_live_place) shared by POST /edits and the replicator.

DO $$
BEGIN
    IF to_regclass('public.live_places') IS NOT NULL THEN
        ALTER TABLE live_places ADD COLUMN IF NOT EXISTS osm_timestamp TIMESTAMPTZ;
        ALTER TABLE live_places ADD COLUMN IF NOT EXISTS deleted BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE live_places ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'replication';
        ALTER TABLE live_places ADD COLUMN IF NOT EXISTS changeset_id BIGINT;
        CREATE INDEX IF NOT EXISTS idx_live_places_osm_timestamp ON live_places (osm_timestamp);
    END IF;
    -- places is owned by pipeline/load_db.py and may not exist on a fresh DB.
    IF to_regclass('public.places') IS NOT NULL THEN
        CREATE INDEX IF NOT EXISTS idx_places_poi_node_id ON places (poi_node_id);
    END IF;
END $$;

CREATE OR REPLACE FUNCTION manara_upsert_live_place(
    p_osm_type TEXT,
    p_osm_id BIGINT,
    p_version INT,
    p_lon DOUBLE PRECISION,
    p_lat DOUBLE PRECISION,
    p_tags JSONB,
    p_deleted BOOLEAN,
    p_osm_ts TIMESTAMPTZ,
    p_source TEXT,
    p_changeset_id BIGINT
) RETURNS BOOLEAN
LANGUAGE plpgsql
AS $fn$
DECLARE
    v_geom geometry;
    v_region TEXT;
BEGIN
    IF p_deleted THEN
        -- Tombstones only for objects we know: keep their last known position.
        SELECT geom INTO v_geom FROM live_places
        WHERE osm_type = p_osm_type AND osm_id = p_osm_id;
        IF v_geom IS NULL THEN
            SELECT geom INTO v_geom FROM places
            WHERE (osm_type = p_osm_type AND osm_id = p_osm_id)
               OR (p_osm_type = 'node' AND poi_node_id = p_osm_id)
            LIMIT 1;
        END IF;
        IF v_geom IS NULL THEN
            RETURN FALSE;
        END IF;
    ELSE
        IF p_lon IS NULL OR p_lat IS NULL THEN
            RETURN FALSE;
        END IF;
        v_geom := ST_SetSRID(ST_Point(p_lon, p_lat), 4326);
    END IF;

    -- The replication bbox also covers Qatar, Bahrain, Kuwait, UAE...: a live
    -- place must fall inside a Saudi region polygon.
    SELECT code INTO v_region FROM regions WHERE ST_Intersects(geom, v_geom) LIMIT 1;
    IF v_region IS NULL AND NOT p_deleted THEN
        RETURN FALSE;
    END IF;

    INSERT INTO live_places (
        osm_type, osm_id, version, geom, region_code, tags, seen_at,
        osm_timestamp, deleted, source, changeset_id
    ) VALUES (
        p_osm_type, p_osm_id, p_version, v_geom, v_region,
        CASE WHEN p_deleted THEN '{}'::jsonb ELSE COALESCE(p_tags, '{}'::jsonb) END,
        NOW(), p_osm_ts, p_deleted, COALESCE(p_source, 'replication'), p_changeset_id
    )
    ON CONFLICT (osm_type, osm_id) DO UPDATE SET
        version = EXCLUDED.version,
        geom = EXCLUDED.geom,
        region_code = COALESCE(EXCLUDED.region_code, live_places.region_code),
        tags = EXCLUDED.tags,
        seen_at = NOW(),
        osm_timestamp = EXCLUDED.osm_timestamp,
        deleted = EXCLUDED.deleted,
        changeset_id = EXCLUDED.changeset_id
    WHERE live_places.version IS NULL
       OR EXCLUDED.version IS NULL
       OR EXCLUDED.version >= live_places.version;

    RETURN FOUND;
END
$fn$;
