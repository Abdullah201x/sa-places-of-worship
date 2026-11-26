from fastapi import APIRouter, Depends, HTTPException
from app.database import get_db

router = APIRouter(prefix="/api/v1", tags=["metadata"])


@router.get("/meta")
def get_metadata(conn=Depends(get_db)):
    with conn.cursor() as cur:
        cur.execute("""
        SELECT version, pbf_date, pbf_timestamp, published_at, metadata
        FROM dataset_versions
        ORDER BY published_at DESC
        LIMIT 1;
        """)
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="No published dataset metadata found.")

        # Also get current live record counts
        cur.execute("SELECT COUNT(*) FROM places;")
        places_count = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) FROM gaps;")
        gaps_count = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) FROM suggestions;")
        suggestions_count = cur.fetchone()["count"]

        pbf_ts = row.get("pbf_timestamp") if isinstance(row, dict) else None
        return {
            "version": row["version"],
            "pbf_date": str(row["pbf_date"]) if row["pbf_date"] else None,
            "pbf_timestamp": pbf_ts.isoformat() if pbf_ts else None,
            "published_at": row["published_at"].isoformat() if row["published_at"] else None,
            "counts": {
                "places": places_count,
                "gaps": gaps_count,
                "suggestions": suggestions_count,
            },
            "summary": row["metadata"],
        }
