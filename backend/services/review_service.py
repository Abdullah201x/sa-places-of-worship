"""
Review service managing persistent reviewer marks, synchronization, and community stats.
"""

import datetime
import sqlite3
from typing import Any, Dict, List, Optional
from backend.database import get_db_connection


class ReviewService:
    @staticmethod
    def get_review(osm_type: str, osm_id: int) -> Optional[Dict[str, Any]]:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM reviews WHERE osm_type = ? AND osm_id = ?",
            (osm_type.lower(), int(osm_id)),
        )
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None

    @staticmethod
    def get_all_reviews(status: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        conn = get_db_connection()
        cur = conn.cursor()
        if status:
            cur.execute("SELECT * FROM reviews WHERE status = ?", (status,))
        else:
            cur.execute("SELECT * FROM reviews")
        rows = cur.fetchall()
        conn.close()

        result = {}
        for r in rows:
            key = f"{r['osm_type']}/{r['osm_id']}"
            result[key] = {
                "status": r["status"],
                "version": r["version"],
                "user_name": r["user_name"],
                "notes": r["notes"],
                "at": int(datetime.datetime.fromisoformat(r["updated_at"]).timestamp() * 1000)
                if r["updated_at"]
                else int(datetime.datetime.now().timestamp() * 1000),
            }
        return result

    @staticmethod
    def set_review(
        osm_type: str,
        osm_id: int,
        status: str,
        version: Optional[int] = None,
        user_id: Optional[int] = None,
        user_name: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        osm_type = osm_type.lower()
        osm_id = int(osm_id)
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO reviews (osm_type, osm_id, status, version, user_id, user_name, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(osm_type, osm_id) DO UPDATE SET
                status = excluded.status,
                version = COALESCE(excluded.version, reviews.version),
                user_id = COALESCE(excluded.user_id, reviews.user_id),
                user_name = COALESCE(excluded.user_name, reviews.user_name),
                notes = COALESCE(excluded.notes, reviews.notes),
                updated_at = excluded.updated_at
            """,
            (osm_type, osm_id, status, version, user_id, user_name, notes, now_str, now_str),
        )

        cur.execute(
            """
            INSERT INTO activity_logs (action_type, osm_type, osm_id, user_name, details, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("review_marked", osm_type, osm_id, user_name, f"Status: {status}", now_str),
        )

        conn.commit()
        conn.close()

        return {
            "osm_type": osm_type,
            "osm_id": osm_id,
            "status": status,
            "version": version,
            "updated_at": now_str,
        }

    @staticmethod
    def clear_review(osm_type: str, osm_id: int, user_name: Optional[str] = None) -> bool:
        osm_type = osm_type.lower()
        osm_id = int(osm_id)
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM reviews WHERE osm_type = ? AND osm_id = ?", (osm_type, osm_id))
        deleted = cur.rowcount > 0

        if deleted:
            cur.execute(
                """
                INSERT INTO activity_logs (action_type, osm_type, osm_id, user_name, details, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("review_cleared", osm_type, osm_id, user_name, "Mark cleared", now_str),
            )
            conn.commit()

        conn.close()
        return deleted

    @staticmethod
    def sync_reviews(client_marks: Dict[str, Any], user_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Two-way synchronization between client marks and server DB.
        Saves incoming client marks into DB, and returns the full updated list of server marks.
        """
        if isinstance(client_marks, dict):
            for key, val in client_marks.items():
                if "/" in key and isinstance(val, dict):
                    parts = key.split("/")
                    osm_type, osm_id_str = parts[0], parts[1]
                    try:
                        osm_id = int(osm_id_str)
                        status = val.get("status", "fixed")
                        version = val.get("version")
                        ReviewService.set_review(
                            osm_type=osm_type,
                            osm_id=osm_id,
                            status=status,
                            version=version,
                            user_name=user_name,
                        )
                    except (ValueError, TypeError):
                        pass

        # Return latest merged state
        server_marks = ReviewService.get_all_reviews()
        stats = ReviewService.get_stats()
        return {
            "marks": server_marks,
            "stats": stats,
        }

    @staticmethod
    def get_stats() -> Dict[str, Any]:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM reviews")
        total = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM reviews WHERE status = 'fixed'")
        fixed = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM reviews WHERE status = 'skipped'")
        skipped = cur.fetchone()[0]

        today_start = datetime.datetime.now(datetime.timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()
        cur.execute("SELECT COUNT(*) FROM reviews WHERE updated_at >= ?", (today_start,))
        reviewed_today = cur.fetchone()[0]

        cur.execute("SELECT COUNT(DISTINCT user_name) FROM reviews WHERE user_name IS NOT NULL")
        reviewers_count = cur.fetchone()[0]

        conn.close()

        return {
            "total_reviews": total,
            "fixed_count": fixed,
            "skipped_count": skipped,
            "reviewed_today": reviewed_today,
            "active_reviewers": reviewers_count,
        }
