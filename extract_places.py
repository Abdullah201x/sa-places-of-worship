import os
import sys
import time

import osmium
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.strtree import STRtree

from common import (BASE_DIR, configure_utf8_output, find_pbf, is_worship_tagged,
                    load_boundary, ring_centroid, update_summary, write_json)

configure_utf8_output()

# Tags taken from a POI node when it is merged into the building it sits in.
POI_TAG_KEYS = ("name", "name:en", "amenity", "religion", "denomination",
                "place_of_worship", "wheelchair", "capacity", "addr:city")


class PlacesOfWorshipExtractor(osmium.SimpleHandler):
    def __init__(self, boundary_prep, bounds):
        super().__init__()
        self.boundary_prep = boundary_prep
        self.minx, self.miny, self.maxx, self.maxy = bounds
        self.nodes = []      # (feature, tags dict)
        self.ways = []       # (feature, tags dict, footprint polygon or None)
        self.relations = []  # feature

    def _inside(self, lon, lat):
        return (self.minx <= lon <= self.maxx and self.miny <= lat <= self.maxy
                and self.boundary_prep.contains(Point(lon, lat)))

    def node(self, n):
        if not n.tags or not is_worship_tagged(n.tags):
            return
        try:
            lon, lat = n.location.lon, n.location.lat
        except osmium.InvalidLocationError:
            return
        if self._inside(lon, lat):
            tags = dict(n.tags)
            self.nodes.append((_create_feature(n.id, lat, lon, tags, "Point", n), tags))

    def way(self, w):
        if not w.tags or not is_worship_tagged(w.tags):
            return
        try:
            coords = [(nd.lon, nd.lat) for nd in w.nodes]
        except osmium.InvalidLocationError:
            return
        centroid = ring_centroid(coords)
        if centroid is None or not self._inside(*centroid):
            return
        footprint = None
        if len(coords) >= 4 and coords[0] == coords[-1]:
            poly = Polygon(coords)
            if poly.is_valid and poly.area > 0:
                footprint = poly
        tags = dict(w.tags)
        feature = _create_feature(w.id, centroid[1], centroid[0], tags, "Polygon", w)
        self.ways.append((feature, tags, footprint))

    def area(self, a):
        # Closed ways are already handled in way(); only multipolygon
        # relations (large mosques with courtyards) are picked up here.
        if a.from_way() or not is_worship_tagged(a.tags):
            return
        try:
            polys = [Polygon([(nd.lon, nd.lat) for nd in ring]) for ring in a.outer_rings()]
        except osmium.InvalidLocationError:
            return
        polys = [p for p in polys if p.is_valid and p.area > 0]
        if not polys:
            return
        geom = MultiPolygon(polys) if len(polys) > 1 else polys[0]
        c = geom.centroid if geom.contains(geom.centroid) else geom.representative_point()
        if self._inside(c.x, c.y):
            self.relations.append(_create_feature(a.orig_id(), c.y, c.x, dict(a.tags), "Relation", a))


def _create_feature(osm_id, lat, lon, tags, geom_type, osm_obj):
    religion = tags.get("religion", "unknown")
    if religion == "unknown":
        if tags.get("building") == "mosque" or tags.get("amenity") == "mosque":
            religion = "muslim"

    properties = {
        "osm_id": osm_id,
        "geom_type": geom_type,
        "name": tags.get("name", ""),
        "name_en": tags.get("name:en", ""),
        "name_original": tags.get("name", ""),
        "name_en_original": tags.get("name:en", ""),
        "religion": religion,
        "denomination": tags.get("denomination", "unknown"),
        "building": tags.get("building", ""),
        "amenity": tags.get("amenity", ""),
        "place_of_worship": tags.get("place_of_worship", ""),
        "wheelchair": tags.get("wheelchair", ""),
        "female": tags.get("female", tags.get("worship:female", tags.get("female_prayer_space", ""))),
        "capacity": tags.get("capacity", ""),
        "addr_city": tags.get("addr:city", ""),
        "last_edited_by": osm_obj.user,
        "user_id": osm_obj.uid,
        "changeset_id": osm_obj.changeset,
        "version": osm_obj.version,
        "edited_at": osm_obj.timestamp.isoformat()
    }
    _apply_name_fallbacks(properties)

    return {
        "type": "Feature",
        "properties": properties,
        "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]}
    }


def _apply_name_fallbacks(properties):
    # Capture any translation if name is empty
    if not properties["name"] and properties["name_en"]:
        properties["name"] = properties["name_en"]
    elif not properties["name_en"] and properties["name"]:
        properties["name_en"] = properties["name"]

    # Default fallback for naming
    if not properties["name"]:
        properties["name"] = "Mosque" if properties["religion"] == "muslim" else "Place of Worship"
        properties["name_en"] = "Mosque" if properties["religion"] == "muslim" else "Place of Worship"


def merge_nodes_into_buildings(nodes, ways):
    """
    A common OSM pattern is a tagged POI node placed inside an (often less
    tagged) building=mosque outline. Extracted separately they show up as two
    mosques, the building gets a false "missing amenity" issue and the node a
    false "mapped as node" one. Merge each such node into the smallest
    footprint containing it: the building keeps its geometry and metadata,
    the node's POI tags fill in, and the node id is kept in poi_node_id so the
    UI can link and edit both objects.

    Returns the list of nodes that were not merged.
    """
    footprints = [(feat, tags, fp) for feat, tags, fp in ways if fp is not None]
    if not footprints:
        return [feat for feat, _ in nodes], 0, 0
    tree = STRtree([fp for _, _, fp in footprints])

    remaining = []
    merged = 0
    duplicates = 0
    for node_feat, node_tags in nodes:
        lon, lat = node_feat["geometry"]["coordinates"]
        pt = Point(lon, lat)
        hits = [i for i in tree.query(pt) if footprints[i][2].contains(pt)
                and "poi_node_id" not in footprints[i][0]["properties"]]
        if not hits:
            remaining.append(node_feat)
            continue

        way_feat, way_tags, _ = footprints[min(hits, key=lambda i: footprints[i][2].area)]
        props = way_feat["properties"]
        node_props = node_feat["properties"]

        # Both objects carry amenity=place_of_worship: the place is mapped
        # twice in OSM, which is itself worth fixing.
        if way_tags.get("amenity") in ("place_of_worship", "mosque") and \
                node_tags.get("amenity") in ("place_of_worship", "mosque"):
            props["duplicate_poi"] = True
            duplicates += 1

        merged_tags = dict(way_tags)
        merged_tags.update({k: node_tags[k] for k in POI_TAG_KEYS if node_tags.get(k)})
        merged_props = _create_feature_props_from(merged_tags, props)
        merged_props["poi_node_id"] = node_props["osm_id"]
        merged_props["poi_node_version"] = node_props["version"]
        way_feat["properties"] = merged_props
        merged += 1

    return remaining, merged, duplicates


def _create_feature_props_from(tags, base_props):
    """Recomputes tag-derived properties from merged tags, keeping the
    building's identity and edit metadata."""
    religion = tags.get("religion", "unknown")
    if religion == "unknown" and (tags.get("building") == "mosque" or tags.get("amenity") == "mosque"):
        religion = "muslim"
    props = dict(base_props)
    props.update({
        "name": tags.get("name", ""),
        "name_en": tags.get("name:en", ""),
        "name_original": tags.get("name", ""),
        "name_en_original": tags.get("name:en", ""),
        "religion": religion,
        "denomination": tags.get("denomination", "unknown"),
        "amenity": tags.get("amenity", ""),
        "place_of_worship": tags.get("place_of_worship", ""),
        "wheelchair": tags.get("wheelchair", ""),
        "capacity": tags.get("capacity", ""),
        "addr_city": tags.get("addr:city", ""),
    })
    _apply_name_fallbacks(props)
    return props


def main():
    pbf_path = find_pbf(BASE_DIR)
    output_path = os.path.join(BASE_DIR, "places_of_worship_sa.geojson")

    print("Loading Saudi Arabia boundary...")
    _, boundary_prep, bounds = load_boundary(BASE_DIR)

    print("Scanning PBF and extracting places of worship inside Saudi Arabia...")
    start_time = time.time()
    extractor = PlacesOfWorshipExtractor(boundary_prep, bounds)
    extractor.apply_file(pbf_path, locations=True)
    print(f"Extraction completed in {time.time() - start_time:.2f} seconds "
          f"({len(extractor.nodes)} nodes, {len(extractor.ways)} ways, {len(extractor.relations)} relations).")

    remaining_nodes, merged, duplicates = merge_nodes_into_buildings(extractor.nodes, extractor.ways)
    print(f"Merged {merged} POI nodes into the building outlines they sit in "
          f"({duplicates} of them double-tagged as the place of worship).")

    features = remaining_nodes + [feat for feat, _, _ in extractor.ways] + extractor.relations
    if not features:
        sys.exit("No places of worship extracted; refusing to overwrite the existing dataset.")

    write_json(output_path, {"type": "FeatureCollection", "features": features})
    update_summary("places", {
        "count": len(features),
        "nodes": len(remaining_nodes),
        "ways": len(extractor.ways),
        "relations": len(extractor.relations),
        "merged_nodes": merged,
    }, pbf_path)

    print(f"Found {len(features)} places of worship inside Saudi Arabia boundaries.")
    print(f"Places of worship written to {output_path}")


if __name__ == "__main__":
    main()
