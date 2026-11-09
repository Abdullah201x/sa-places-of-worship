-- 002_unique_nulls_constraints.sql
-- Enforce UNIQUE NULLS NOT DISTINCT for existing databases if not already present

DO $$
BEGIN
    IF to_regclass('public.tag_usage_history') IS NOT NULL THEN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'uq_tag_usage_history_version_key_val'
        ) THEN
            BEGIN
                ALTER TABLE tag_usage_history
                ADD CONSTRAINT uq_tag_usage_history_version_key_val
                UNIQUE NULLS NOT DISTINCT (dataset_version, tag_key, tag_value);
            EXCEPTION WHEN duplicate_table OR duplicate_object THEN
                NULL;
            END;
        END IF;
    END IF;

    IF to_regclass('public.change_events') IS NOT NULL THEN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'uq_change_events_source_type_id_ver_cs'
        ) THEN
            BEGIN
                ALTER TABLE change_events
                ADD CONSTRAINT uq_change_events_source_type_id_ver_cs
                UNIQUE NULLS NOT DISTINCT (source, osm_type, osm_id, version_after, changeset_id);
            EXCEPTION WHEN duplicate_table OR duplicate_object THEN
                NULL;
            END;
        END IF;
    END IF;
END $$;
