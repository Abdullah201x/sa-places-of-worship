"""
Database schema management for Manara Phase 4 tables:
users, sessions, review_marks, review_events, and edits.
"""


def init_app_tables(conn):
    """Ensure Phase 4 tables and their indexes exist."""
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            osm_uid BIGINT PRIMARY KEY,
            display_name TEXT NOT NULL,
            avatar_url TEXT,
            osm_changesets INT NOT NULL DEFAULT 0,
            osm_account_created TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_login_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            leaderboard_opt_in BOOLEAN NOT NULL DEFAULT FALSE,
            is_admin BOOLEAN NOT NULL DEFAULT FALSE
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            osm_uid BIGINT NOT NULL REFERENCES users(osm_uid) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL,
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions (expires_at);
        CREATE INDEX IF NOT EXISTS idx_sessions_osm_uid ON sessions (osm_uid);

        CREATE TABLE IF NOT EXISTS review_marks (
            osm_type VARCHAR(16) NOT NULL,
            osm_id BIGINT NOT NULL,
            osm_uid BIGINT NOT NULL REFERENCES users(osm_uid) ON DELETE CASCADE,
            status VARCHAR(32) NOT NULL,
            version INT NOT NULL,
            verified_changeset BIGINT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (osm_type, osm_id, osm_uid)
        );
        CREATE INDEX IF NOT EXISTS idx_review_marks_type_id ON review_marks (osm_type, osm_id);
        CREATE INDEX IF NOT EXISTS idx_review_marks_status ON review_marks (status);
        CREATE INDEX IF NOT EXISTS idx_review_marks_uid ON review_marks (osm_uid);

        CREATE TABLE IF NOT EXISTS review_events (
            id SERIAL PRIMARY KEY,
            osm_type VARCHAR(16) NOT NULL,
            osm_id BIGINT NOT NULL,
            osm_uid BIGINT NOT NULL,
            status VARCHAR(32) NOT NULL,
            version INT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_review_events_osm ON review_events (osm_type, osm_id);

        CREATE TABLE IF NOT EXISTS edits (
            changeset_id BIGINT PRIMARY KEY,
            osm_uid BIGINT NOT NULL REFERENCES users(osm_uid) ON DELETE CASCADE,
            objects JSONB NOT NULL DEFAULT '[]'::jsonb,
            comment TEXT NOT NULL DEFAULT '',
            verified_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_edits_osm_uid ON edits (osm_uid);
        CREATE INDEX IF NOT EXISTS idx_edits_created_at ON edits (created_at DESC);

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

        CREATE TABLE IF NOT EXISTS change_events (
            id BIGSERIAL PRIMARY KEY,
            source TEXT NOT NULL,
            confirmed BOOLEAN DEFAULT FALSE,
            reverted_same_day BOOLEAN DEFAULT FALSE,
            osm_timestamp TIMESTAMPTZ,
            observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            changeset_id BIGINT,
            replication_seq BIGINT,
            dataset_version TEXT,
            prev_dataset_version TEXT,
            osm_type TEXT NOT NULL,
            osm_id BIGINT NOT NULL,
            prev_ref TEXT,
            kind TEXT NOT NULL,
            flags JSONB DEFAULT '[]'::jsonb,
            geom GEOMETRY(Point, 4326),
            region_code TEXT,
            name TEXT DEFAULT '',
            tag_diff JSONB DEFAULT '{}'::jsonb,
            version_before INT,
            version_after INT
        );
        CREATE INDEX IF NOT EXISTS idx_change_events_osm ON change_events (osm_type, osm_id);
        CREATE INDEX IF NOT EXISTS idx_change_events_observed ON change_events (observed_at DESC);
        CREATE INDEX IF NOT EXISTS idx_change_events_region ON change_events (region_code);
        CREATE INDEX IF NOT EXISTS idx_change_events_source ON change_events (source);

        CREATE TABLE IF NOT EXISTS change_triage (
            change_id BIGINT PRIMARY KEY REFERENCES change_events(id) ON DELETE CASCADE,
            status TEXT NOT NULL,
            osm_uid BIGINT REFERENCES users(osm_uid) ON DELETE SET NULL,
            note TEXT DEFAULT '',
            triaged_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS replication_state (
            id INT PRIMARY KEY DEFAULT 1,
            sequence BIGINT NOT NULL,
            osm_timestamp TIMESTAMPTZ NOT NULL,
            processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_gap_from BIGINT,
            last_gap_to BIGINT,
            last_gap_at TIMESTAMPTZ
        );

        CREATE TABLE IF NOT EXISTS live_places (
            osm_type TEXT NOT NULL,
            osm_id BIGINT NOT NULL,
            version INT,
            geom GEOMETRY(Point, 4326),
            tags JSONB DEFAULT '{}'::jsonb,
            seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (osm_type, osm_id)
        );

        CREATE TABLE IF NOT EXISTS live_pending (
            osm_type TEXT NOT NULL,
            osm_id BIGINT NOT NULL,
            version INT,
            tags JSONB DEFAULT '{}'::jsonb,
            node_refs BIGINT[] DEFAULT '{}'::bigint[],
            seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (osm_type, osm_id)
        );

        CREATE TABLE IF NOT EXISTS tag_usage_history (
            id SERIAL PRIMARY KEY,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            dataset_version TEXT NOT NULL,
            tag_key TEXT NOT NULL,
            tag_value TEXT,
            count INT NOT NULL,
            total_places INT NOT NULL,
            with_keys JSONB DEFAULT '{}'::jsonb,
            UNIQUE (dataset_version, tag_key, tag_value)
        );

        CREATE INDEX IF NOT EXISTS idx_tag_usage_key ON tag_usage_history (tag_key, tag_value);

        CREATE TABLE IF NOT EXISTS sprints (
            id SERIAL PRIMARY KEY,
            slug TEXT UNIQUE NOT NULL,
            title JSONB NOT NULL,
            instructions JSONB NOT NULL DEFAULT '{}'::jsonb,
            theme TEXT NOT NULL DEFAULT 'worship',
            area JSONB NOT NULL,
            rule_ids TEXT[] DEFAULT '{}'::text[],
            gap_min_urgency INT,
            hashtag TEXT NOT NULL,
            starts_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            ends_at TIMESTAMPTZ,
            status TEXT NOT NULL DEFAULT 'draft',
            created_by BIGINT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_sprints_status ON sprints (status);
        CREATE INDEX IF NOT EXISTS idx_sprints_slug ON sprints (slug);

        CREATE TABLE IF NOT EXISTS sprint_tiles (
            sprint_id INT NOT NULL REFERENCES sprints(id) ON DELETE CASCADE,
            tile_id TEXT NOT NULL,
            bbox REAL[] NOT NULL,
            state TEXT NOT NULL DEFAULT 'ready',
            rev INT NOT NULL DEFAULT 1,
            workload INT NOT NULL DEFAULT 0,
            pending_refresh BOOLEAN NOT NULL DEFAULT FALSE,
            lock_uid BIGINT,
            lock_display_name TEXT,
            lock_kind TEXT,
            lock_expires_at TIMESTAMPTZ,
            mapped_by BIGINT,
            validated_by BIGINT,
            skip_reason TEXT,
            note TEXT,
            auto BOOLEAN NOT NULL DEFAULT FALSE,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (sprint_id, tile_id)
        );

        CREATE INDEX IF NOT EXISTS idx_sprint_tiles_sprint_state ON sprint_tiles (sprint_id, state);
        CREATE INDEX IF NOT EXISTS idx_sprint_tiles_lock ON sprint_tiles (lock_uid, lock_expires_at);

        CREATE TABLE IF NOT EXISTS tile_events (
            id SERIAL PRIMARY KEY,
            sprint_id INT NOT NULL REFERENCES sprints(id) ON DELETE CASCADE,
            tile_id TEXT NOT NULL,
            osm_uid BIGINT NOT NULL,
            from_state TEXT NOT NULL,
            to_state TEXT NOT NULL,
            reason TEXT,
            note TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_tile_events_sprint_tile ON tile_events (sprint_id, tile_id);
        CREATE INDEX IF NOT EXISTS idx_tile_events_created_at ON tile_events (created_at DESC);
        """)

