-- 001_retention_indexes.sql
-- Optimizes indexes for session cleanup and retention pruning

CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions (expires_at);
CREATE INDEX IF NOT EXISTS idx_review_events_created_at ON review_events (created_at);
CREATE INDEX IF NOT EXISTS idx_tile_events_created_at ON tile_events (created_at);
