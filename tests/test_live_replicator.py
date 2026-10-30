import pytest
import sys
import os
from unittest.mock import MagicMock

pipeline_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "pipeline"))
if pipeline_dir not in sys.path:
    sys.path.insert(0, pipeline_dir)

from live_replicator import (
    parse_state_txt,
    format_sequence_path,
    build_diff_url,
    is_in_sa_bbox,
    parse_osc_stream,
    record_live_events,
    load_known_places,
)


def test_parse_state_txt():
    sample = """# Osmosis replication state
sequenceNumber=6123456
timestamp=2026-10-30T00\\:15\\:00Z
"""
    res = parse_state_txt(sample)
    assert res["sequence"] == 6123456
    assert res["timestamp"] == "2026-10-30T00:15:00Z"


def test_format_sequence_path():
    assert format_sequence_path(6123456) == "006/123/456"
    assert format_sequence_path(1) == "000/000/001"


def test_build_diff_url():
    url = build_diff_url("https://planet.openstreetmap.org/replication/minute", 6123456)
    assert url == "https://planet.openstreetmap.org/replication/minute/006/123/456.osc.gz"


def test_is_in_sa_bbox():
    # Riyadh: ~24.71, 46.67
    assert is_in_sa_bbox(24.71, 46.67) is True
    # Makkah: ~21.38, 39.85
    assert is_in_sa_bbox(21.38, 39.85) is True
    # London: ~51.5, -0.1
    assert is_in_sa_bbox(51.5, -0.1) is False
    # Tokyo: ~35.6, 139.6
    assert is_in_sa_bbox(35.6, 139.6) is False


def test_parse_osc_stream():
    osc_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<osmChange version="0.6" generator="Osmosis">
  <create>
    <node id="998877" version="1" timestamp="2026-10-30T00:10:00Z" uid="123" user="spammer" changeset="554433" lat="24.7136" lon="46.6753">
      <tag k="amenity" v="place_of_worship"/>
      <tag k="religion" v="muslim"/>
      <tag k="name" v="\xd9\x85\xd8\xb3\xd8\xac\xd8\xaf \xd8\xa7\xd9\x84\xd8\xa8\xd8\xb1\xd9\x83\xd8\xa9"/>
    </node>
    <!-- Non-worship node inside KSA should be ignored -->
    <node id="111222" version="1" changeset="554433" lat="24.7" lon="46.6">
      <tag k="amenity" v="restaurant"/>
    </node>
    <!-- Worship node outside KSA should be ignored -->
    <node id="333444" version="1" changeset="554433" lat="51.5" lon="-0.1">
      <tag k="amenity" v="place_of_worship"/>
      <tag k="name" v="London Mosque"/>
    </node>
  </create>
</osmChange>
"""
    events = parse_osc_stream(osc_xml)
    assert len(events) == 1
    ev = events[0]
    assert ev["kind"] == "created"
    assert ev["osm_type"] == "node"
    assert ev["osm_id"] == 998877
    assert ev["changeset_id"] == 554433
    assert ev["name"] == "مسجد البركة"
    # Verify user and uid were stripped completely
    assert "user" not in ev
    assert "uid" not in ev


def test_record_live_events():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_conn.transaction.return_value.__enter__.return_value = mock_conn

    events = [
        {
            "source": "live",
            "kind": "created",
            "osm_type": "node",
            "osm_id": 998877,
            "version_after": 1,
            "version_before": None,
            "changeset_id": 554433,
            "name": "مسجد البركة",
            "lat": 24.7136,
            "lon": 46.6753,
            "tags": {"amenity": "place_of_worship"},
            "flags": [],
        }
    ]

    record_live_events(mock_conn, 6123456, "2026-10-30T00:15:00Z", events)
    assert mock_cur.execute.call_count == 2  # 1 event insert + 1 replication_state update


WAYS_OSC = b"""<?xml version="1.0" encoding="UTF-8"?>
<osmChange version="0.6">
  <create>
    <node id="1" version="1" changeset="9" lat="24.70" lon="46.60"/>
    <node id="2" version="1" changeset="9" lat="24.72" lon="46.62"/>
    <node id="3" version="1" changeset="9" lat="51.50" lon="-0.10"/>
    <!-- worship way placed by nodes in this diff, inside SA -->
    <way id="100" version="1" changeset="9">
      <nd ref="1"/><nd ref="2"/>
      <tag k="amenity" v="place_of_worship"/><tag k="name" v="Riyadh Mosque"/>
    </way>
    <!-- worship way placed by nodes in this diff, outside SA -->
    <way id="101" version="1" changeset="9">
      <nd ref="3"/>
      <tag k="amenity" v="place_of_worship"/><tag k="name" v="London Mosque"/>
    </way>
    <!-- worship way whose nodes are not in this diff -->
    <way id="102" version="1" changeset="9">
      <nd ref="999"/>
      <tag k="amenity" v="place_of_worship"/>
    </way>
  </create>
  <modify>
    <!-- known place that lost its worship tags -->
    <way id="200" version="4" changeset="9">
      <nd ref="777"/><tag k="building" v="yes"/>
    </way>
  </modify>
  <delete>
    <!-- known place deleted: no tags, no coordinates -->
    <way id="300" version="5" changeset="9"/>
    <!-- unknown way deleted somewhere in the world -->
    <way id="301" version="2" changeset="9"/>
    <relation id="302" version="2" changeset="9"/>
  </delete>
</osmChange>
"""

KNOWN = {
    ("way", 200): {"lat": 21.4, "lon": 39.8},
    ("way", 300): {"lat": 26.4, "lon": 50.1},
}


def test_parse_osc_stream_drops_unlocatable_worldwide_objects():
    pending = []
    events = parse_osc_stream(WAYS_OSC, known_places=KNOWN, pending=pending)
    keys = {(e["osm_type"], e["osm_id"]): e for e in events}

    # placed from diff nodes inside SA
    assert keys[("way", 100)]["lat"] == pytest.approx(24.71)
    assert keys[("way", 100)]["lon"] == pytest.approx(46.61)
    # known places keep their cached position, even deleted or untagged
    assert keys[("way", 300)]["kind"] == "deleted"
    assert (keys[("way", 300)]["lat"], keys[("way", 300)]["lon"]) == (26.4, 50.1)
    assert keys[("way", 200)]["kind"] == "modified"
    # outside SA, unknown deletions and unplaceable ways never become events
    assert ("way", 101) not in keys
    assert ("way", 301) not in keys
    assert ("relation", 302) not in keys
    assert ("way", 102) not in keys
    assert all(e["lat"] is not None and e["lon"] is not None for e in events)
    # the unplaceable worship way is parked for the daily run
    assert [(p["osm_type"], p["osm_id"], p["node_refs"]) for p in pending] == [("way", 102, [999])]


def test_parse_osc_stream_without_cache_drops_all_deletions_and_unplaced_ways():
    events = parse_osc_stream(WAYS_OSC)
    assert {(e["osm_type"], e["osm_id"]) for e in events} == {("way", 100)}


def test_load_known_places_reads_places_and_live_places():
    cur = MagicMock()
    cur.fetchall.side_effect = [
        [{"osm_type": "way", "osm_id": 5, "lat": 24.7, "lon": 46.6}],
        [("node", 6, 21.4, 39.8)],
    ]
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    known = load_known_places(conn)
    assert known == {
        ("way", 5): {"lat": 24.7, "lon": 46.6},
        ("node", 6): {"lat": 21.4, "lon": 39.8},
    }
