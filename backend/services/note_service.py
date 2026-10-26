"""
Note service managing community field notes and place comments in SQLite.
"""

import datetime
from typing import Any, Dict, List, Optional
from backend.database import get_db_connection


class NoteService:
    @staticmethod
    def get_notes(osm_type: str, osm_id: int) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM place_notes
            WHERE osm_type = ? AND osm_id = ?
            ORDER BY created_at DESC
            """,
            (osm_type.lower(), int(osm_id)),
        )
        rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def add_note(
        osm_type: str,
        osm_id: int,
        user_name: str,
        content: str,
        tags: Optional[str] = None,
    ) -> Dict[str, Any]:
        osm_type = osm_type.lower()
        osm_id = int(osm_id)
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO place_notes (osm_type, osm_id, user_name, content, tags, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (osm_type, osm_id, user_name.strip() or "مساهم", content.strip(), tags, now_str),
        )
        note_id = cur.lastrowid

        cur.execute(
            """
            INSERT INTO activity_logs (action_type, osm_type, osm_id, user_name, details, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("note_added", osm_type, osm_id, user_name, content[:100], now_str),
        )

        conn.commit()
        conn.close()

        return {
            "id": note_id,
            "osm_type": osm_type,
            "osm_id": osm_id,
            "user_name": user_name,
            "content": content,
            "tags": tags,
            "created_at": now_str,
        }

    @staticmethod
    def get_recent_notes(limit: int = 50) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM place_notes
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]
