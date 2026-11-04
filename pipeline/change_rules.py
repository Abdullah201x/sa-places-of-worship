"""
Change feed rules and flag definitions for Manara.

Shared between the daily change detector (pipeline/detect_changes.py)
and the live minutely replicator (manara-live).
"""

from typing import Any

from worship_tags import is_worship_tagged


CHANGE_FLAGS = {
    "deleted-named-mosque": {
        "severity": "high",
        "title_ar": "حذف مكان عبادة مسمى",
        "title_en": "Named place of worship deleted",
        "description_ar": "تم حذف مكان عبادة يحمل اسماً ولم يُرصد كترقية إلى رسم مبنى.",
        "description_en": "A named place of worship was deleted and not matched as an upgrade.",
    },
    "name-removed": {
        "severity": "high",
        "title_ar": "إزالة الاسم",
        "title_en": "Name removed",
        "description_ar": "كان المكان يحمل اسماً وتمت إزالته في التعديل الأخير.",
        "description_en": "Place previously had a name which was removed in the latest edit.",
    },
    "religion-changed": {
        "severity": "high",
        "title_ar": "تغيير الديانة",
        "title_en": "Religion changed",
        "description_ar": "تم تغيير قيمة وسم الديانة (religion).",
        "description_en": "The religion tag was modified to a different value.",
    },
    "amenity-removed": {
        "severity": "high",
        "title_ar": "إزالة وسم مكان العبادة",
        "title_en": "Amenity tag removed",
        "description_ar": "تمت إزالة amenity=place_of_worship.",
        "description_en": "amenity=place_of_worship was removed.",
    },
    "new-duplicate": {
        "severity": "medium",
        "title_ar": "احتمال تكرار مكان موجود",
        "title_en": "Potential duplicate",
        "description_ar": "مكان جديد يقع على بعد أقل من 50 متراً من مكان قائم وباسم متطابق أو متقارب.",
        "description_en": "New place within 50 m of an existing one with a matching or similar name.",
    },
    "name-ar-mismatch": {
        "severity": "medium",
        "title_ar": "تعارض بين name و name:ar",
        "title_en": "Mismatch between name and name:ar",
        "description_ar": "كلا الوسمين name و name:ar محددين ولكن بنصوص مختلفة بعد التوحيد القياسي.",
        "description_en": "Both name and name:ar are set but differ after Arabic normalization.",
    },
    "left-boundary": {
        "severity": "medium",
        "title_ar": "انتقال خارج حدود المملكة",
        "title_en": "Moved outside Saudi Arabia",
        "description_ar": "انتقل موقع المكان إلى خارج حدود المملكة العربية السعودية.",
        "description_en": "Place coordinates moved outside the Saudi Arabia boundary polygon.",
    },
    "moved-far": {
        "severity": "medium",
        "title_ar": "تحريك المعلم لمسافة بعيدة",
        "title_en": "Moved significantly (>200m)",
        "description_ar": "تم تغيير موقع المعلم بأكثر من 200 متر عن موقعه السابق.",
        "description_en": "Centroid moved by more than 200 metres from its previous location.",
    },
    "building-downgraded": {
        "severity": "low",
        "title_ar": "تخفيض تصنيف المبنى",
        "title_en": "Building tag downgraded",
        "description_ar": "تم تغيير building=mosque إلى building=yes.",
        "description_en": "building=mosque was downgraded to building=yes.",
    },
    "issue-fixed": {
        "severity": "info",
        "title_ar": "تم إصلاح ملاحظة جودة",
        "title_en": "QA issue resolved",
        "description_ar": "تم إصلاح ملاحظة فحص جودة كانت موجودة سابقاً.",
        "description_en": "A previously recorded QA rule violation has been resolved.",
    },
}


def compute_tag_diff(old_tags: dict[str, Any], new_tags: dict[str, Any]) -> dict[str, Any]:
    """
    Computes a clean dictionary of added, modified, and removed tags.
    """
    diff: dict[str, Any] = {"added": {}, "modified": {}, "removed": {}}
    old_keys = set(old_tags.keys()) if old_tags else set()
    new_keys = set(new_tags.keys()) if new_tags else set()

    for k in new_keys - old_keys:
        diff["added"][k] = new_tags[k]

    for k in old_keys - new_keys:
        diff["removed"][k] = old_tags[k]

    for k in old_keys & new_keys:
        if str(old_tags[k]).strip() != str(new_tags[k]).strip():
            diff["modified"][k] = {"before": old_tags[k], "after": new_tags[k]}

    # Omit empty sections
    return {k: v for k, v in diff.items() if v}


def evaluate_change_flags(
    old_tags: dict[str, Any] | None,
    new_tags: dict[str, Any] | None,
    is_deleted: bool = False,
    is_upgraded: bool = False,
    is_outside_boundary: bool = False,
    is_potential_duplicate: bool = False,
    is_moved_far: bool = False,
    normalized_name: str = "",
    normalized_name_ar: str = "",
    resolved_issues: list[str] | None = None,
) -> list[str]:
    """
    Evaluates which flags apply to an edit event.
    Returns a list of flag identifiers.
    """
    flags = []
    old_tags = old_tags or {}
    new_tags = new_tags or {}

    old_name = (old_tags.get("name") or old_tags.get("name:ar") or "").strip()
    new_name = (new_tags.get("name") or new_tags.get("name:ar") or "").strip()

    # 1. deleted-named-mosque
    if is_deleted and old_name and not is_upgraded:
        flags.append("deleted-named-mosque")

    if not is_deleted:
        # 2. name-removed
        if old_name and not new_name:
            flags.append("name-removed")

        # 3. religion-changed
        old_rel = old_tags.get("religion", "").strip()
        new_rel = new_tags.get("religion", "").strip()
        if old_rel and new_rel and old_rel != new_rel:
            flags.append("religion-changed")

        # 4. amenity-removed
        old_amenity = old_tags.get("amenity")
        new_amenity = new_tags.get("amenity")
        if old_amenity == "place_of_worship" and new_amenity != "place_of_worship":
            flags.append("amenity-removed")

        # 5. building-downgraded
        old_bld = old_tags.get("building")
        new_bld = new_tags.get("building")
        if old_bld == "mosque" and new_bld == "yes":
            flags.append("building-downgraded")

        # 6. name-ar-mismatch
        name_val = (new_tags.get("name") or "").strip()
        name_ar_val = (new_tags.get("name:ar") or "").strip()
        if name_val and name_ar_val and normalized_name and normalized_name_ar:
            if normalized_name != normalized_name_ar:
                flags.append("name-ar-mismatch")

        # 7. left-boundary
        if is_outside_boundary:
            flags.append("left-boundary")

        # 8. new-duplicate
        if is_potential_duplicate:
            flags.append("new-duplicate")

        # 9. moved-far
        if is_moved_far:
            flags.append("moved-far")

    # 10. issue-fixed
    if resolved_issues and len(resolved_issues) > 0:
        flags.append("issue-fixed")

    return flags
