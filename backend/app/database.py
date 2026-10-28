import os
from typing import Generator
from fastapi import HTTPException
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DATABASE_URL = os.environ.get("MANARA_DATABASE_URL") or os.environ.get("DATABASE_URL")

pool: ConnectionPool | None = None


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
