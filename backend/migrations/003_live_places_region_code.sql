-- 003_live_places_region_code.sql
-- Add region_code column to live_places if not already present

DO $$
BEGIN
    IF to_regclass('public.live_places') IS NOT NULL THEN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name = 'live_places' AND column_name = 'region_code'
        ) THEN
            ALTER TABLE live_places ADD COLUMN region_code TEXT;
        END IF;
    END IF;
END $$;
