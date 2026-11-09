import os
import sys
from unittest.mock import MagicMock, call
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))

from app.database import run_migrations
from load_db import run_retention_cleanup


def test_run_migrations_applies_unapplied(tmp_path):
    # Setup dummy migrations
    mig1 = tmp_path / "001_test.sql"
    mig1.write_text("CREATE TABLE test_table (id INT);", encoding="utf-8")
    mig2 = tmp_path / "002_test.sql"
    mig2.write_text("ALTER TABLE test_table ADD COLUMN name TEXT;", encoding="utf-8")

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchall.return_value = []  # None applied yet

    applied = run_migrations(mock_conn, migrations_dir=str(tmp_path))

    assert applied == ["001_test.sql", "002_test.sql"]
    executed_statements = [c[0][0] for c in mock_cur.execute.call_args_list]
    assert any("CREATE TABLE test_table" in s for s in executed_statements)
    assert any("ALTER TABLE test_table" in s for s in executed_statements)


def test_run_migrations_skips_already_applied(tmp_path):
    mig1 = tmp_path / "001_test.sql"
    mig1.write_text("CREATE TABLE test_table (id INT);", encoding="utf-8")
    mig2 = tmp_path / "002_test.sql"
    mig2.write_text("ALTER TABLE test_table ADD COLUMN name TEXT;", encoding="utf-8")

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchall.return_value = [{"id": "001_test.sql"}]

    applied = run_migrations(mock_conn, migrations_dir=str(tmp_path))

    assert applied == ["002_test.sql"]


def test_run_retention_cleanup():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.rowcount = 3

    run_retention_cleanup(mock_conn, retention_days=180)

    executed = [c[0][0] for c in mock_cur.execute.call_args_list]
    assert any("DELETE FROM sessions" in s for s in executed)
    assert any("DELETE FROM review_events" in s for s in executed)
    assert any("DELETE FROM tile_events" in s for s in executed)
