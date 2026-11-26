"""Worship-tag predicate; a copy of pipeline/worship_tags.is_worship_tagged.

The backend image doesn't ship pipeline/, so the 3-line rule is duplicated.
tests/test_live_places.py checks both stay identical.
"""


def is_worship_tagged(tags: dict) -> bool:
    if not tags:
        return False
    amenity = tags.get("amenity")
    return amenity in ("place_of_worship", "mosque") or tags.get("building") == "mosque"
