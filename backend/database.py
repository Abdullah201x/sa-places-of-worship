"""
SQLite Database manager for Saudi Places of Worship Map backend.
Manages schema creation, thread-safe connections, and queries.
"""

import os
import sqlite3
import datetime
from backend.config import Config


def get_db_connection(db_path=None):
    """Returns a SQLite connection with row factory enabled."""
    if db_path is None:
        try:
            from flask import current_app
            db_path = current_app.config.get("DB_PATH", Config.DB_PATH)
        except (RuntimeError, ImportError):
            db_path = Config.DB_PATH

    path = db_path or Config.DB_PATH
    conn = sqlite3.connect(path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    # Enable foreign keys and WAL mode for better concurrency
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def init_db(db_path=None):
    """Initializes tables and indexes if they do not exist."""
    conn = get_db_connection(db_path)
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        osm_type TEXT NOT NULL,
        osm_id INTEGER NOT NULL,
        status TEXT NOT NULL,  -- 'fixed', 'skipped', 'needs_work'
        version INTEGER,
        user_id INTEGER,
        user_name TEXT,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(osm_type, osm_id)
    );

    CREATE INDEX IF NOT EXISTS idx_reviews_type_id ON reviews(osm_type, osm_id);
    CREATE INDEX IF NOT EXISTS idx_reviews_status ON reviews(status);
    CREATE INDEX IF NOT EXISTS idx_reviews_updated ON reviews(updated_at);

    CREATE TABLE IF NOT EXISTS place_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        osm_type TEXT NOT NULL,
        osm_id INTEGER NOT NULL,
        user_name TEXT NOT NULL,
        content TEXT NOT NULL,
        tags TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_notes_place ON place_notes(osm_type, osm_id);

    CREATE TABLE IF NOT EXISTS activity_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action_type TEXT NOT NULL,
        osm_type TEXT,
        osm_id INTEGER,
        user_name TEXT,
        details TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_logs(created_at);

    CREATE TABLE IF NOT EXISTS pipeline_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status TEXT NOT NULL,
        pbf_date TEXT,
        details TEXT
    );
    """)

    conn.commit()
    conn.close()
