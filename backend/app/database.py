import contextlib
import os
from typing import Generator
from fastapi import HTTPException
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DATABASE_URL = os.environ.get("MANARA_DATABASE_URL") or os.environ.get("DATABASE_URL")

pool: ConnectionPool | None = None


@contextlib.contextmanager
def get_db_context():
    """Acquires a database connection, respecting FastAPI test dependency overrides if active."""
    try:
        from app.main import app
        if get_db in app.dependency_overrides:
            gen = app.dependency_overrides[get_db]()
            conn = next(gen)
            try:
                yield conn
            finally:
                try:
                    next(gen)
                except StopIteration:
                    pass
            return
    except Exception:
        pass

    global pool
    if pool is None:
        raise HTTPException(status_code=503, detail="Database connection is not available. Please verify DATABASE_URL.")
    with pool.connection() as conn:
        yield conn


def init_pool():
    global pool
    if not DATABASE_URL:
        print("[WARN] DATABASE_URL is not set. Database queries will fail.")
        return
    pool = ConnectionPool(
        conninfo=DATABASE_URL,
        min_size=1,
        max_size=10,
        kwargs={"row_factory": dict_row, "autocommit": True},
        # Test each connection before handing it out, so connections killed by
        # a database restart (e.g. when Coolify applies a config change) are
        # replaced instead of failing the request with a 500.
        check=ConnectionPool.check_connection,
        open=True,
    )
    print("[INFO] Database connection pool initialized.")


def close_pool():
    global pool
    if pool is not None:
        pool.close()
        pool = None
        print("[INFO] Database connection pool closed.")


def get_db():
    global pool
    if pool is None:
        raise HTTPException(status_code=503, detail="Database connection is not available. Please verify DATABASE_URL.")
    with pool.connection() as conn:
        yield conn


def run_migrations(conn, migrations_dir=None):
    """Executes unapplied SQL migration files in alphanumeric order."""
    if migrations_dir is None:
        migrations_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "migrations"))

    applied = []
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id VARCHAR(64) PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)

        cur.execute("SELECT id FROM schema_migrations;")
        already_applied = {row["id"] if isinstance(row, dict) else row[0] for row in cur.fetchall()}

        if not os.path.isdir(migrations_dir):
            return applied

        sql_files = sorted(f for f in os.listdir(migrations_dir) if f.endswith(".sql"))
        for filename in sql_files:
            if filename in already_applied:
                continue
            filepath = os.path.join(migrations_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                sql_content = f.read()

            if sql_content.strip():
                cur.execute(sql_content)
            cur.execute("INSERT INTO schema_migrations (id) VALUES (%s);", (filename,))
            applied.append(filename)
            print(f"[INFO] Applied database migration: {filename}")

    return applied

