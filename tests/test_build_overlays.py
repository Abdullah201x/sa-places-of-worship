import gzip
import json
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))

import pmtiles_writer
from pmtiles_writer import lonlat_to_world, zxy_to_tileid
from build_overlays import (
    create_pmtiles_v3_header,
    write_fallback_pmtiles,
    build_all_overlays,
)


def _read_varint(b, pos):
    n = shift = 0
    while True:
        c = b[pos]
        pos += 1
        n |= (c & 0x7F) << shift
        if c < 0x80:
            return n, pos
        shift += 7


def read_archive(path):
    """Minimal PMTiles v3 reader: returns (header dict, metadata, {tile_id: gzip tile bytes})."""
    raw = open(path, "rb").read()
    assert raw[:8] == b"PMTiles\x03"
    names = ["root_off", "root_len", "meta_off", "meta_len", "leaf_off", "leaf_len",
             "data_off", "data_len", "addressed", "entries", "contents"]
    h = dict(zip(names, struct.unpack_from("<11Q", raw, 8)))
    meta = json.loads(gzip.decompress(raw[h["meta_off"]:h["meta_off"] + h["meta_len"]]))

    def read_dir(blob):
        buf = gzip.decompress(blob)
        count, pos = _read_varint(buf, 0)
        ids, last = [], 0
        for _ in range(count):
            d, pos = _read_varint(buf, pos)
            last += d
            ids.append(last)
        runs, lengths, offsets = [], [], []
        for _ in range(count):
            v, pos = _read_varint(buf, pos)
            runs.append(v)
        for _ in range(count):
            v, pos = _read_varint(buf, pos)
            lengths.append(v)
        for i in range(count):
            v, pos = _read_varint(buf, pos)
            offsets.append(offsets[-1] + lengths[i - 1] if v == 0 and i else v - 1)
        return list(zip(ids, offsets, lengths, runs))

    tiles = {}
    for tid, off, length, run in read_dir(raw[h["root_off"]:h["root_off"] + h["root_len"]]):
        if run == 0:  # points at a leaf directory
            leaf = raw[h["leaf_off"] + off:h["leaf_off"] + off + length]
            for t2, o2, l2, r2 in read_dir(leaf):
                assert r2 == 1
                tiles[t2] = raw[h["data_off"] + o2:h["data_off"] + o2 + l2]
        else:
            tiles[tid] = raw[h["data_off"] + off:h["data_off"] + off + length]
    return h, meta, tiles


def decode_points(gz):
    """Decodes our single-layer MVT point tiles into [(x, y, props)]."""
    buf = gzip.decompress(gz)

    def fields(b):
        pos = 0
        while pos < len(b):
            key, pos = _read_varint(b, pos)
            field, wire = key >> 3, key & 7
            if wire == 0:
                v, pos = _read_varint(b, pos)
            elif wire == 1:
                v, pos = b[pos:pos + 8], pos + 8
            else:
                n, pos = _read_varint(b, pos)
                v, pos = b[pos:pos + n], pos + n
            yield field, v

    layer = next(v for f, v in fields(buf) if f == 3)
    keys, values, feats = [], [], []
    for f, v in fields(layer):
        if f == 3:
            keys.append(v.decode())
        elif f == 4:
            [(vf, vv)] = list(fields(v))
            values.append(vv.decode() if vf == 1 else struct.unpack("<d", vv)[0] if vf == 3 else vv)
        elif f == 2:
            feats.append(v)

    def unzigzag(n):
        return (n >> 1) ^ -(n & 1)

    out = []
    for feat in feats:
        tags, geom = [], b""
        for f, v in fields(feat):
            if f == 2:
                p = 0
                while p < len(v):
                    t, p = _read_varint(v, p)
                    tags.append(t)
            elif f == 4:
                geom = v
        cmd, p = _read_varint(geom, 0)
        assert cmd == 9  # MoveTo, count 1
        zx, p = _read_varint(geom, p)
        zy, p = _read_varint(geom, p)
        props = {keys[tags[i]]: values[tags[i + 1]] for i in range(0, len(tags), 2)}
        out.append((unzigzag(zx), unzigzag(zy), props))
    return out


def tile_zoom(tid):
    z = 0
    while tid >= ((1 << (2 * (z + 1))) - 1) // 3:
        z += 1
    return z


def test_create_pmtiles_v3_header():
    header = create_pmtiles_v3_header()
    assert len(header) == 127
    assert header.startswith(b"PMTiles\x03")


def test_tile_ids_follow_the_hilbert_curve():
    assert zxy_to_tileid(0, 0, 0) == 0
    assert [zxy_to_tileid(1, x, y) for x, y in ((0, 0), (0, 1), (1, 1), (1, 0))] == [1, 2, 3, 4]
    assert zxy_to_tileid(2, 0, 0) == 5


def test_write_fallback_pmtiles_without_points(tmp_path):
    output_path = tmp_path / "test.pmtiles"
    write_fallback_pmtiles(str(output_path), "test_layer", min_zoom=6, max_zoom=12)

    _h, meta, tiles = read_archive(output_path)
    assert tiles == {}
    assert meta["name"] == "test_layer"
    assert meta["minzoom"] == 6
    assert meta["maxzoom"] == 12
    assert meta["vector_layers"][0]["id"] == "test_layer"


def test_fallback_writes_real_decodable_tiles(tmp_path):
    out = tmp_path / "pts.pmtiles"
    pts = [
        (46.675, 24.713, {"name": "مسجد", "osm_id": 7, "score": 1.5, "empty": ""}, 0),
        (39.6, 24.47, {"name": "B", "osm_id": 8}, 0),
    ]
    write_fallback_pmtiles(str(out), "pts", min_zoom=4, max_zoom=8, points=pts)

    h, meta, tiles = read_archive(out)
    assert h["addressed"] == len(tiles) > 0
    assert meta["vector_layers"][0]["fields"] == {"name": "String", "osm_id": "Number", "score": "Number"}

    x, y = lonlat_to_world(46.675, 24.713, 8)
    got = decode_points(tiles[zxy_to_tileid(8, int(x), int(y))])
    riyadh = [p for p in got if p[2]["osm_id"] == 7]
    assert len(riyadh) == 1
    px, py, props = riyadh[0]
    assert props == {"name": "مسجد", "osm_id": 7, "score": 1.5}  # the empty string is dropped
    assert abs(px - (x - int(x)) * 4096) <= 1
    assert abs(py - (y - int(y)) * 4096) <= 1


def test_low_zooms_thin_points_but_the_top_zoom_keeps_all(tmp_path):
    # Two points about 20 m apart: one pixel at z5, two distinct pixels at z14.
    pts = [(46.0, 24.0, {"id": 1}, 1), (46.0002, 24.0, {"id": 2}, 5)]
    out = tmp_path / "thin.pmtiles"
    write_fallback_pmtiles(str(out), "thin", min_zoom=5, max_zoom=14, points=pts)
    _h, _m, tiles = read_archive(out)

    def ids_at(z):
        return {props["id"] for tid, data in tiles.items() if tile_zoom(tid) == z
                for _x, _y, props in decode_points(data)}

    assert ids_at(5) == {2}  # the higher-priority point wins
    assert ids_at(14) == {1, 2}


def test_large_archives_use_leaf_directories(tmp_path, monkeypatch):
    monkeypatch.setattr(pmtiles_writer, "ROOT_DIR_BUDGET", 600)
    monkeypatch.setattr(pmtiles_writer, "LEAF_SIZES", (50, 200))
    pts = [(34.6 + i * 0.01, 16.4 + (i % 50) * 0.01, {"i": i}, 0) for i in range(2000)]
    out = tmp_path / "many.pmtiles"
    write_fallback_pmtiles(str(out), "many", min_zoom=10, max_zoom=12, points=pts)

    h, _m, tiles = read_archive(out)
    assert h["leaf_len"] > 0
    assert len(tiles) == h["addressed"]
    assert {p[2]["i"] for d in tiles.values() for p in decode_points(d)} == set(range(2000))


def test_build_all_overlays_with_fallback(tmp_path):
    (tmp_path / "places_of_worship_sa.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {"osm_id": 1, "name": "X", "geom_type": "Polygon", "secret": "dropped"},
        "geometry": {"type": "Point", "coordinates": [46.7, 24.7]}}]}), encoding="utf-8")
    (tmp_path / "worship_gaps_sa.json").write_text(
        json.dumps({"grid_size": 0.004, "cells": [[11675, 6175, 300, 12.5, 40.0]]}), encoding="utf-8")
    (tmp_path / "suggested_mosques_sa.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")

    ok = build_all_overlays(data_dir=str(tmp_path))
    assert ok is True

    assert (tmp_path / "places.pmtiles").exists()
    assert (tmp_path / "gaps.pmtiles").exists()
    assert (tmp_path / "suggestions.pmtiles").exists()

    _h, _m, tiles = read_archive(tmp_path / "places.pmtiles")
    props = [p[2] for d in tiles.values() for p in decode_points(d)]
    assert props and all(p == {"osm_id": 1, "name": "X", "osm_type": "way"} for p in props)  # untrimmed keys never reach the tiles

    _h, _m, tiles = read_archive(tmp_path / "gaps.pmtiles")
    assert any(p[2]["urgency"] == 40.0 for d in tiles.values() for p in decode_points(d))
