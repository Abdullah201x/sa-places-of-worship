"""
Shared worship-tag predicate for Manara.

Used by extract_places.py, the minutely replicator (manara-live),
and the daily diff engine (detect_changes.py) to ensure they never disagree.
"""


def is_worship_tagged(tags: dict) -> bool:
    """
    Returns True if the OSM tags qualify the object as a place of worship.
    Matches:
      - amenity=place_of_worship
      - amenity=mosque
      - building=mosque
    """
    if not tags:
        return False
    amenity = tags.get("amenity")
    return amenity in ("place_of_worship", "mosque") or tags.get("building") == "mosque"


def is_mosque(tags: dict) -> bool:
    """
    Returns True if the place is specifically an Islamic place of worship
    (mosque, musalla, jami').
    """
    if not is_worship_tagged(tags):
        return False
    religion = tags.get("religion", "muslim")
    return religion == "muslim"


def worship_religion(tags: dict) -> str:
    """Returns the religion tag or 'unknown'."""
    if not tags:
        return "unknown"
    return tags.get("religion") or "unknown"


def worship_denomination(tags: dict) -> str:
    """Returns the denomination tag or 'unknown'."""
    if not tags:
        return "unknown"
    return tags.get("denomination") or "unknown"
