import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))

from load_db import update_sprint_workloads


def test_update_sprint_workloads_no_sprints_table():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchone.return_value = None  # to_regclass returns None

    update_sprint_workloads(conn)

    assert cur.execute.call_count == 1
    assert "to_regclass" in cur.execute.call_args[0][0]


def test_update_sprint_workloads_no_active_sprints():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchone.return_value = ("sprints",)  # to_regclass succeeds
    cur.fetchall.return_value = []  # no active sprints

    update_sprint_workloads(conn)

    assert cur.execute.call_count == 2
    assert "status IN ('draft', 'active')" in cur.execute.call_args[0][0]


def test_update_sprint_workloads_active_sprints_with_published_dataset():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur

    now = datetime.now(timezone.utc)

    # Sequence of fetchone / fetchall:
    # 1. to_regclass -> ('sprints',)
    # 2. fetchall active_sprints -> [(1, 'test-sprint', ['missing_name_en'], 5)]
    # 3. fetchone published_at -> (now,)
    cur.fetchone.side_effect = [
        ("sprints",),
        (now,),
    ]
    cur.fetchall.return_value = [
        (1, "test-sprint", ["missing_name_en"], 5),
    ]

    update_sprint_workloads(conn)

    # Verify that workload update and pending_refresh queries were executed
    executed_queries = [call[0][0] for call in cur.execute.call_args_list]

    assert any("UPDATE sprint_tiles st" in q and "workload =" in q for q in executed_queries)
    assert any("UPDATE sprint_tiles st" in q and "pending_refresh =" in q for q in executed_queries)


def test_update_sprint_workloads_without_published_date():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur

    cur.fetchone.side_effect = [
        ("sprints",),
        None,  # no dataset_versions recorded
    ]
    cur.fetchall.return_value = [
        (2, "draft-sprint", None, None),
    ]

    update_sprint_workloads(conn)

    executed_queries = [call[0][0] for call in cur.execute.call_args_list]
    assert any("UPDATE sprint_tiles st" in q and "workload =" in q for q in executed_queries)
    assert any("UPDATE sprint_tiles SET pending_refresh = FALSE WHERE sprint_id = %s" in q for q in executed_queries)
