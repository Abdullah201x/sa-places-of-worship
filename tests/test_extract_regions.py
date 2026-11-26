import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))

from extract_regions import RegionRelationCollector


class DummyRelation:
    def __init__(self, rel_id, tags, members):
        self.id = rel_id
        self.tags = tags
        self.members = members


class DummyMember:
    def __init__(self, m_type, ref, role):
        self.type = m_type
        self.ref = ref
        self.role = role


def test_region_collector_identifies_saudi_province():
    c = RegionRelationCollector()
    rel = DummyRelation(
        3678409,
        {
            "boundary": "administrative",
            "admin_level": "4",
            "ISO3166-2": "SA-01",
            "name": "منطقة الرياض",
            "name:en": "Riyadh Region",
        },
        [
            DummyMember("w", 101, "outer"),
            DummyMember("w", 102, "outer"),
            DummyMember("w", 103, "inner"),
            DummyMember("n", 201, "admin_centre"),
        ]
    )
    c.relation(rel)

    assert 3678409 in c.regions
    assert c.regions[3678409]["code"] == "SA-01"
    assert c.regions[3678409]["name"] == "منطقة الرياض"
    assert c.regions[3678409]["ways"] == {101, 102}
    assert c.all_way_ids == {101, 102}


def test_region_collector_ignores_non_admin4_or_non_sa():
    c = RegionRelationCollector()
    # admin_level 2 (Country)
    c.relation(DummyRelation(307584, {"boundary": "administrative", "admin_level": "2", "ISO3166-2": "SA"}, [DummyMember("w", 1, "outer")]))
    # Other country (e.g. QA-DA)
    c.relation(DummyRelation(27332, {"boundary": "administrative", "admin_level": "4", "ISO3166-2": "QA-DA"}, [DummyMember("w", 2, "outer")]))
    # Not administrative
    c.relation(DummyRelation(9999, {"boundary": "national_park", "admin_level": "4", "ISO3166-2": "SA-01"}, [DummyMember("w", 3, "outer")]))

    assert len(c.regions) == 0
    assert len(c.all_way_ids) == 0
