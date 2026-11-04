import math
import os
import time

import osmium
from shapely.geometry import Point, Polygon

from common import (BASE_DIR, find_pbf, is_worship_tagged, load_boundary, ring_centroid,
                    to_metres, update_summary, write_json)

# Default thresholds used only for the console summary below; the actual
# too_small/too_large classification now happens client-side in app.js so
# users can tune the range interactively. Every matched footprint's area is
# written out, not just the outliers under these defaults.
DEFAULT_MIN_AREA_M2 = 20      # smaller than a small prayer room -> likely a mis-mapped footprint
DEFAULT_MAX_AREA_M2 = 15000   # bigger than almost all neighborhood/city mosques -> likely merged buildings or an oversized outline

class MosqueSizeExtractor(osmium.SimpleHandler):
    def __init__(self, boundary_prep, bounds):
        super().__init__()
        self.boundary_prep = boundary_prep
        self.minx, self.miny, self.maxx, self.maxy = bounds
        self.sizes = {}

    def way(self, w):
        tags = w.tags
        if not tags:
            return
        if tags.get('place_of_worship') == 'musalla':
            return  # Eid musallas are legitimately large open areas, not size outliers
        # building=yes alone matches every ordinary building in the extract (houses,
        # shops, ...), so it only counts here when paired with an amenity tag that
        # actually marks the way as a place of worship. building=mosque needs no such
        # pairing since that tag value is mosque-specific on its own.
        if not is_worship_tagged(tags):
            return
        try:
            coords = [(node.lon, node.lat) for node in w.nodes]
        except osmium.InvalidLocationError:
            return
        if len(coords) < 4:
            return  # not a closed ring, can't compute an area

        centroid_lon, centroid_lat = ring_centroid(coords)
        if not (self.minx <= centroid_lon <= self.maxx and self.miny <= centroid_lat <= self.maxy):
            return
        if not self.boundary_prep.contains(Point(centroid_lon, centroid_lat)):
            return

        m_lon = 111_320.0 * math.cos(math.radians(centroid_lat))
        m_lat = 110_574.0
        coords_m = [(x * m_lon, y * m_lat) for x, y in coords]
        area_m2 = Polygon(coords_m).area
        if area_m2 <= 0:
            return

        self.sizes[str(w.id)] = {"area_m2": round(area_m2, 1)}

    def area(self, a):
        if a.from_way() or not is_worship_tagged(a.tags):
            return
        if a.tags.get('place_of_worship') == 'musalla':
            return
        polys = []
        try:
            for outer in a.outer_rings():
                shell = [(nd.lon, nd.lat) for nd in outer]
                holes = [[(nd.lon, nd.lat) for nd in inner] for inner in a.inner_rings(outer)]
                p = Polygon(shell, holes=holes)
                if not p.is_valid:
                    p = p.buffer(0)
                if p.is_valid and p.area > 0:
                    polys.append(p)
        except osmium.InvalidLocationError:
            return
        if not polys:
            return

        total_m2 = 0.0
        for p in polys:
            c_lat = p.centroid.y
            m_lon = 111_320.0 * math.cos(math.radians(c_lat))
            m_lat = 110_574.0
            shell_m = [(x * m_lon, y * m_lat) for x, y in p.exterior.coords]
            holes_m = [[(x * m_lon, y * m_lat) for x, y in h.coords] for h in p.interiors]
            poly_m = Polygon(shell_m, holes=holes_m)
            total_m2 += poly_m.area

        if total_m2 > 0:
            self.sizes[str(a.orig_id())] = {"area_m2": round(total_m2, 1)}

def main():
    pbf_path = find_pbf(BASE_DIR)
    output_path = os.path.join(BASE_DIR, "mosque_sizes.json")

    print("Loading Saudi Arabia boundary...")
    _, boundary_prep, bounds = load_boundary(BASE_DIR)

    print("Scanning PBF for mosque building footprints inside Saudi Arabia...")
    start_time = time.time()

    extractor = MosqueSizeExtractor(boundary_prep, bounds)
    extractor.apply_file(pbf_path, locations=True)

    duration = time.time() - start_time
    print(f"Scan completed in {duration:.2f} seconds.")

    too_small = sum(1 for v in extractor.sizes.values() if v["area_m2"] < DEFAULT_MIN_AREA_M2)
    too_large = sum(1 for v in extractor.sizes.values() if v["area_m2"] > DEFAULT_MAX_AREA_M2)
    print(f"Computed area for {len(extractor.sizes)} footprints "
          f"({too_small} under {DEFAULT_MIN_AREA_M2}m2, {too_large} over {DEFAULT_MAX_AREA_M2}m2 by default).")

    write_json(output_path, extractor.sizes)
    update_summary("sizes", {"count": len(extractor.sizes)}, pbf_path)

    print(f"Mosque building footprint areas written to {output_path}")

if __name__ == "__main__":
    main()
