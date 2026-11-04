import csv
import gzip
import json
import os
import struct
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))

from validate_data import (
    validate_pmtiles_header,
    validate_regions_count,
    validate_tag_stats_sanity,
    validate_csv_integrity,
    validate_manifest_integrity,
    validate_all,
    sha256_file,
)


def _make_dummy_pmtiles(path, magic=b"PMTiles\x03", addressed_tiles=10, fill_size=200):
    """Writes a dummy PMTiles v3 binary file with specified magic and addressed tile count."""
    header = bytearray(127)
    header[: len(magic)] = magic
    # Write 11 uint64s at offset 8:
    # 0: root_off, 1: root_len, 2: meta_off, 3: meta_len, 4: leaf_off, 5: leaf_len,
    # 6: data_off, 7: data_len, 8: addressed, 9: entries, 10: contents
    fields = [127, 32, 159, 10, 0, 0, 169, 50, addressed_tiles, addressed_tiles, 1]
    struct.pack_into("<11Q", header, 8, *fields)
    with open(path, "wb") as f:
        f.write(header)
        if fill_size > 127:
            f.write(b"\x00" * (fill_size - 127))


def test_validate_pmtiles_valid(tmp_path):
    pmtiles_file = tmp_path / "valid.pmtiles"
    _make_dummy_pmtiles(str(pmtiles_file), addressed_tiles=42)
    valid, msg = validate_pmtiles_header(str(pmtiles_file), min_size=127)
    assert valid is True
    assert "42" in msg


def test_validate_pmtiles_invalid_magic(tmp_path):
    pmtiles_file = tmp_path / "bad_magic.pmtiles"
    _make_dummy_pmtiles(str(pmtiles_file), magic=b"BADMAGIC")
    valid, msg = validate_pmtiles_header(str(pmtiles_file), min_size=127)
    assert valid is False
    assert "invalid PMTiles magic header" in msg


def test_validate_pmtiles_zero_addressed(tmp_path):
    pmtiles_file = tmp_path / "zero_tiles.pmtiles"
    _make_dummy_pmtiles(str(pmtiles_file), addressed_tiles=0)
    valid, msg = validate_pmtiles_header(str(pmtiles_file), min_size=127)
    assert valid is False
    assert "0 addressed tiles" in msg


def test_validate_pmtiles_truncated(tmp_path):
    pmtiles_file = tmp_path / "short.pmtiles"
    pmtiles_file.write_bytes(b"PMTiles\x03" + b"\x00" * 20)
    valid, msg = validate_pmtiles_header(str(pmtiles_file), min_size=127)
    assert valid is False
    assert "below minimum expected" in msg


def test_validate_regions_count(tmp_path):
    reg_file = tmp_path / "sa_regions.geojson"

    # Exactly 13 regions
    reg_file.write_text(
        json.dumps({"type": "FeatureCollection", "features": [{"id": f"SA-{i:02d}"} for i in range(1, 14)]}),
        encoding="utf-8",
    )
    assert validate_regions_count(str(tmp_path)) == []

    # 12 regions (shrinkage or missing region)
    reg_file.write_text(
        json.dumps({"type": "FeatureCollection", "features": [{"id": f"SA-{i:02d}"} for i in range(1, 13)]}),
        encoding="utf-8",
    )
    errors = validate_regions_count(str(tmp_path))
    assert len(errors) == 1
    assert "expected exactly 13" in errors[0]


def test_validate_tag_stats_sanity(tmp_path):
    tag_file = tmp_path / "tag_stats_sa.json"

    # Realistic: 6.9%
    tag_file.write_text(
        json.dumps({
            "total_places": 14022,
            "keys": {"name:en": {"count": 968, "percentage": 6.9}},
        }),
        encoding="utf-8",
    )
    assert validate_tag_stats_sanity(str(tmp_path)) == []

    # Synthetic fallback regression: 100%
    tag_file.write_text(
        json.dumps({
            "total_places": 14022,
            "keys": {"name:en": {"count": 14022, "percentage": 100.0}},
        }),
        encoding="utf-8",
    )
    errors = validate_tag_stats_sanity(str(tmp_path))
    assert len(errors) == 1
    assert "synthetic fallback regression" in errors[0]

    # Extreme drop: 0.05%
    tag_file.write_text(
        json.dumps({
            "total_places": 14022,
            "keys": {"name:en": {"count": 5, "percentage": 0.04}},
        }),
        encoding="utf-8",
    )
    errors = validate_tag_stats_sanity(str(tmp_path))
    assert len(errors) == 1
    assert "suspiciously low" in errors[0]


def test_validate_csv_integrity(tmp_path):
    csv_file = tmp_path / "places_of_worship_sa.csv"

    # Valid CSV with UTF-8 BOM
    with open(csv_file, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "osm_type", "osm_id", "name"])
        writer.writerow(["node/123", "node", "123", "مسجد النور"])
        writer.writerow(["way/456", "way", "456", "جامع الفردوس"])
    assert validate_csv_integrity(str(tmp_path)) == []

    # Missing osm_type column
    with open(csv_file, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "osm_id", "name"])
        writer.writerow(["node/123", "123", "مسجد النور"])
    errors = validate_csv_integrity(str(tmp_path))
    assert any("missing osm_type" in e for e in errors)

    # Empty IDs
    with open(csv_file, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "osm_type", "osm_id", "name"])
        writer.writerow(["", "node", "123", "مسجد النور"])
    errors = validate_csv_integrity(str(tmp_path))
    assert any("missing 'id'" in e for e in errors)


def test_validate_manifest_integrity(tmp_path):
    sample_file = tmp_path / "test.json"
    sample_file.write_text('{"status": "ok"}', encoding="utf-8")
    actual_sha = sha256_file(str(sample_file))
    actual_bytes = os.path.getsize(str(sample_file))

    # Matching manifest
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(
        json.dumps({
            "files": [
                {"path": "test.json", "bytes": actual_bytes, "sha256": actual_sha}
            ]
        }),
        encoding="utf-8",
    )
    assert validate_manifest_integrity(str(tmp_path)) == []

    # Corrupt SHA-256
    manifest_file.write_text(
        json.dumps({
            "files": [
                {"path": "test.json", "bytes": actual_bytes, "sha256": "0" * 64}
            ]
        }),
        encoding="utf-8",
    )
    errors = validate_manifest_integrity(str(tmp_path))
    assert len(errors) == 1
    assert "SHA-256 mismatch" in errors[0]

    # Missing file
    manifest_file.write_text(
        json.dumps({
            "files": [
                {"path": "nonexistent.json", "bytes": 100, "sha256": actual_sha}
            ]
        }),
        encoding="utf-8",
    )
    errors = validate_manifest_integrity(str(tmp_path))
    assert len(errors) == 1
    assert "references missing file" in errors[0]
