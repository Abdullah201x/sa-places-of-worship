"""
Dependency-free point tiler: Mapbox Vector Tiles packed into a PMTiles v3 archive.

build_overlays.py prefers tippecanoe. This module is the fallback for hosts
that do not have it (Windows dev machines, the slim pipeline image when the
apt package is missing), so the overlays always contain real tiles. It only
handles Point features, which is all Manara's three overlays are.

Specs:
  PMTiles v3  https://github.com/protomaps/PMTiles/blob/main/spec/v3/spec.md
  MVT 2.1     https://github.com/mapbox/vector-tile-spec/tree/master/2.1
"""

import gzip
import json
import math
import struct
from collections import defaultdict

EXTENT = 4096
# Points this close to a tile edge are also written into the neighbour so that
# circles are not cut in half at tile borders (tippecanoe uses 5 px of 256).
BUFFER = 80
# Below the top zoom, keep one point per THIN_CELL x THIN_CELL block of the tile
# (the highest-priority one). 32 of 4096 is about 2 px on a 256 px tile.
THIN_CELL = 32

HEADER_LEN = 127
ROOT_DIR_BUDGET = 16384 - HEADER_LEN  # the spec wants header + root in the first 16 KiB
LEAF_SIZES = (4096, 8192, 16384, 32768, 65536)


# ---------------------------------------------------------------- tile ids

def zxy_to_tileid(z, x, y):
    """Position of tile z/x/y on the Hilbert curve across all zoom levels."""
    acc = ((1 << (2 * z)) - 1) // 3
    n = 1 << z
    d = 0
    s = n // 2
    while s > 0:
        rx = 1 if (x & s) > 0 else 0
        ry = 1 if (y & s) > 0 else 0
        d += s * s * ((3 * rx) ^ ry)
        if ry == 0:
            if rx == 1:
                x = n - 1 - x
                y = n - 1 - y
            x, y = y, x
        s //= 2
    return acc + d


def lonlat_to_world(lon, lat, z):
    """Web Mercator position in tile units (x right, y down) at zoom z."""
    lat = max(-85.0511287798, min(85.0511287798, lat))
    n = 1 << z
    x = (lon + 180.0) / 360.0 * n
    rad = math.radians(lat)
    y = (1.0 - math.log(math.tan(rad) + 1.0 / math.cos(rad)) / math.pi) / 2.0 * n
    return x, y


# ---------------------------------------------------------------- protobuf

def _varint(n):
    n &= 0xFFFFFFFFFFFFFFFF
    out = bytearray()
    while n > 0x7F:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)


def _zigzag(n):
    return (n << 1) ^ (n >> 63)


def _len_field(field, payload):
    return _varint((field << 3) | 2) + _varint(len(payload)) + payload


def _value_message(v):
    if isinstance(v, bool):
        return _varint((7 << 3) | 0) + _varint(1 if v else 0)
    if isinstance(v, int):
        if v >= 0:
            return _varint((5 << 3) | 0) + _varint(v)  # uint_value
        return _varint((6 << 3) | 0) + _varint(_zigzag(v))  # sint_value
    if isinstance(v, float):
        return _varint((3 << 3) | 1) + struct.pack("<d", v)  # double_value
    return _len_field(1, str(v).encode("utf-8"))  # string_value


def encode_tile(layer_name, points):
    """
    points: iterable of (x, y, props) with x, y already in tile extent units
    (they may lie slightly outside 0..EXTENT because of the buffer).
    Returns the uncompressed MVT bytes.
    """
    keys = {}
    values = {}
    features = []
    for x, y, props in points:
        tags = []
        for k, v in props.items():
            if v is None or v == "":
                continue
            ki = keys.setdefault(k, len(keys))
            vkey = (type(v), v)
            vi = values.get(vkey)
            if vi is None:
                vi = values[vkey] = len(values)
            tags += [ki, vi]
        geom = _varint(9) + _varint(_zigzag(x)) + _varint(_zigzag(y))  # MoveTo(1)
        feat = b""
        if tags:
            feat += _len_field(2, b"".join(_varint(t) for t in tags))
        feat += _varint((3 << 3) | 0) + _varint(1)  # type = POINT
        feat += _len_field(4, geom)
        features.append(feat)

    layer = _varint((15 << 3) | 0) + _varint(2)  # version 2
    layer += _len_field(1, layer_name.encode("utf-8"))
    for f in features:
        layer += _len_field(2, f)
    for k in keys:
        layer += _len_field(3, k.encode("utf-8"))
    for v, _ in sorted(((v, i) for v, i in values.items()), key=lambda t: t[1]):
        layer += _len_field(4, _value_message(v[1]))
    layer += _varint((5 << 3) | 0) + _varint(EXTENT)
    return _len_field(3, layer)


# ---------------------------------------------------------------- tiling

def tile_points(points, min_zoom, max_zoom):
    """
    points: list of (lon, lat, props, priority); higher priority wins when thinning.
    Yields (z, x, y, [(px, py, props), ...]) in no particular order.
    """
    ordered = sorted(points, key=lambda p: -p[3])
    for z in range(min_zoom, max_zoom + 1):
        n = 1 << z
        thin = z < max_zoom
        tiles = defaultdict(list)
        taken = set()
        for lon, lat, props, _prio in ordered:
            wx, wy = lonlat_to_world(lon, lat, z)
            tx, ty = int(wx), int(wy)
            if tx >= n or ty >= n or tx < 0 or ty < 0:
                continue
            px = int(round((wx - tx) * EXTENT))
            py = int(round((wy - ty) * EXTENT))
            if thin:
                cell = (tx, ty, px // THIN_CELL, py // THIN_CELL)
                if cell in taken:
                    continue
                taken.add(cell)
            tiles[(tx, ty)].append((px, py, props))
            # Edge buffer: repeat the point in the neighbouring tiles.
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    nx, ny = tx + dx, ty + dy
                    if not (0 <= nx < n and 0 <= ny < n):
                        continue
                    ox, oy = px - dx * EXTENT, py - dy * EXTENT
                    if -BUFFER <= ox <= EXTENT + BUFFER and -BUFFER <= oy <= EXTENT + BUFFER:
                        tiles[(nx, ny)].append((ox, oy, props))
        for (x, y), pts in tiles.items():
            yield z, x, y, pts


# ---------------------------------------------------------------- archive

def _serialize_directory(entries):
    """entries: sorted list of (tile_id, offset, length, run_length)."""
    out = bytearray(_varint(len(entries)))
    last = 0
    for tid, _o, _l, _r in entries:
        out += _varint(tid - last)
        last = tid
    for _t, _o, _l, run in entries:
        out += _varint(run)
    for _t, _o, length, _r in entries:
        out += _varint(length)
    prev_end = None
    for _t, offset, length, _r in entries:
        if prev_end is not None and offset == prev_end:
            out += _varint(0)
        else:
            out += _varint(offset + 1)
        prev_end = offset + length
    return gzip.compress(bytes(out))


def _build_directories(entries):
    """Returns (root_bytes, leaf_bytes). Splits into leaf directories if needed."""
    root = _serialize_directory(entries)
    if len(root) <= ROOT_DIR_BUDGET:
        return root, b""
    for size in LEAF_SIZES:
        leaves = b""
        root_entries = []
        for i in range(0, len(entries), size):
            chunk = _serialize_directory(entries[i:i + size])
            root_entries.append((entries[i][0], len(leaves), len(chunk), 0))
            leaves += chunk
        root = _serialize_directory(root_entries)
        if len(root) <= ROOT_DIR_BUDGET:
            return root, leaves
    raise ValueError("PMTiles root directory does not fit in 16 KiB")


def write_pmtiles(path, layer_name, points, min_zoom, max_zoom, bounds, center, extra_meta=None,
                  header_builder=None):
    """
    Tiles `points` ((lon, lat, props, priority) tuples) and writes a PMTiles v3
    archive. `header_builder` is build_overlays.create_pmtiles_v3_header.
    Returns the number of tiles written.
    """
    blobs = []  # (tile_id, gzip bytes)
    for z, x, y, pts in tile_points(points, min_zoom, max_zoom):
        blobs.append((zxy_to_tileid(z, x, y), gzip.compress(encode_tile(layer_name, pts), 6)))
    blobs.sort(key=lambda b: b[0])

    entries = []
    offset = 0
    for tid, data in blobs:
        entries.append((tid, offset, len(data), 1))
        offset += len(data)
    tile_data = b"".join(d for _t, d in blobs)

    metadata = {
        "name": layer_name,
        "description": f"Manara {layer_name} vector overlay",
        "version": "1.0",
        "type": "overlay",
        "format": "pbf",
        "minzoom": min_zoom,
        "maxzoom": max_zoom,
        "bounds": ",".join(str(b) for b in bounds),
        "center": f"{center[0]},{center[1]},{center[2]}",
        "vector_layers": [{
            "id": layer_name,
            "minzoom": min_zoom,
            "maxzoom": max_zoom,
            "fields": _field_types(points),
        }],
        "generator": "manara pmtiles_writer",
    }
    if extra_meta:
        metadata.update(extra_meta)
    meta_gz = gzip.compress(json.dumps(metadata, ensure_ascii=False).encode("utf-8"))

    root, leaves = _build_directories(entries)
    root_offset = HEADER_LEN
    meta_offset = root_offset + len(root)
    leaf_offset = meta_offset + len(meta_gz)
    data_offset = leaf_offset + len(leaves)

    header = header_builder(
        root_dir_offset=root_offset, root_dir_len=len(root),
        metadata_offset=meta_offset, metadata_len=len(meta_gz),
        leaf_dir_offset=leaf_offset, leaf_dir_len=len(leaves),
        tile_data_offset=data_offset, tile_data_len=len(tile_data),
        num_addressed_tiles=len(entries), num_tile_entries=len(entries),
        num_tile_contents=len(entries),
        min_zoom=min_zoom, max_zoom=max_zoom,
        min_lon=bounds[0], min_lat=bounds[1], max_lon=bounds[2], max_lat=bounds[3],
        center_zoom=center[2], center_lon=center[0], center_lat=center[1],
    )
    with open(path, "wb") as f:
        f.write(header)
        f.write(root)
        f.write(meta_gz)
        f.write(leaves)
        f.write(tile_data)
    return len(entries)


def _field_types(points):
    seen = {}
    for _lon, _lat, props, _p in points:
        for k, v in props.items():
            if v is None or v == "":
                continue
            if isinstance(v, bool):
                t = "Boolean"
            elif isinstance(v, (int, float)):
                t = "Number"
            else:
                t = "String"
            seen.setdefault(k, t)
    return seen
