# خارطة الكثافة وفجوات التغطية لأماكن العبادة — Saudi Places of Worship Map

An interactive, offline-processed map of places of worship across Saudi Arabia,
plus a "coverage gaps" analysis highlighting inhabited grid cells (by road
density) that contain **zero** places of worship.

The front-end is a static Leaflet dashboard (Arabic, RTL). All heavy data
processing happens ahead of time in Python from an OpenStreetMap `.pbf` extract.

## Contents

| File | Purpose |
|------|---------|
| [extract_sa_boundary.py](file:///c:/Users/abdul/Desktop/GCC20260707/extract_sa_boundary.py) | Builds the Saudi Arabia boundary polygon from OSM. |
| [extract_places.py](file:///c:/Users/abdul/Desktop/GCC20260707/extract_places.py) | Extracts all `amenity=place_of_worship` features inside the boundary. |
| [calculate_gaps.py](file:///c:/Users/abdul/Desktop/GCC20260707/calculate_gaps.py) | Grids the country and flags road-populated cells with no worship place. |
| [index.html](file:///c:/Users/abdul/Desktop/GCC20260707/index.html) / [app.js](file:///c:/Users/abdul/Desktop/GCC20260707/app.js) / [index.css](file:///c:/Users/abdul/Desktop/GCC20260707/index.css) | The Leaflet dashboard front-end. |
| [comparison_results.md](file:///c:/Users/abdul/Desktop/GCC20260707/comparison_results.md) | Comparison report for dataset updates. |
| `*.geojson` | Generated data consumed by the front-end. |

## Prerequisites

- Python 3.9+
- Python packages:

  ```bash
  pip install osmium shapely
  ```

- Exactly one OSM `.pbf` extract covering Saudi Arabia, saved in this folder
  (e.g. a GCC-states extract from Geofabrik). The scripts auto-detect it by
  globbing for `*.osm.pbf`, so no filename is hardcoded — just drop in the
  new extract and remove the old one when updating data.

## Data pipeline

Run the scripts **in this order** (each reads the previous step's output). All
paths are resolved relative to the script location, so no arguments are needed:

```bash
python extract_sa_boundary.py     # -> sa_boundary.geojson
python extract_places.py          # -> places_of_worship_sa.geojson
python calculate_gaps.py          # -> worship_gaps_sa.geojson
```

Notes:
- The Saudi Arabia boundary uses OSM relation id **307584**
  ([extract_sa_boundary.py](file:///c:/Users/abdul/Desktop/GCC20260707/extract_sa_boundary.py)).
- The gap grid uses ~0.004° cells (~440 m, close to typical neighborhood
  mosque spacing). A cell qualifies as a candidate when it contains at least
  2 distinct drivable ways (so a single road passing through empty land
  doesn't count as inhabited). A candidate cell is then flagged as a "gap"
  based on its actual distance to the nearest place of worship (via a
  `shapely` STRtree nearest-neighbor query), not just whether one exists
  somewhere in the same cell. Cells within walking distance (750 m) of a
  mosque are excluded; gap intensity scales with both how far the nearest
  mosque actually is and the cell's total drivable road **length** (summed
  per cell, with through-traffic classes like motorway/trunk/primary
  downweighted). Length is used instead of a raw way count for this
  intensity score because OSM fragments ways into many short segments
  wherever a tag changes (speed limit, lanes, name), which otherwise
  inflates apparent density in cities without indicating more residents
  ([calculate_gaps.py](file:///c:/Users/abdul/Desktop/GCC20260707/calculate_gaps.py)).

## Running the front-end

The app loads GeoJSON via `fetch`, which requires HTTP (it will **not** work by
opening `index.html` directly over `file://`). Serve the folder locally:

```bash
python -m http.server 8000
```

Then open <http://localhost:8000/> in a browser.

## Dataset Updates & Statistics

The database has been updated to the latest OpenStreetMap data:
- **Total Places of Worship:** 12,796 (an increase of +6 additions from 12,790).
- **Active Coverage Gaps:** 60,835 (resolved 6 gaps from the previous dataset).

Detailed information about the changes (including specific coordinates, names, and OSM IDs of added/modified places of worship and gap grid differences) can be found in [comparison_results.md](file:///c:/Users/abdul/Desktop/GCC20260707/comparison_results.md).

## Front-end features

- **كثافة الأماكن (POI density):** heatmap + clustered markers, filterable by
  religion, searchable by name/city/OSM id.
- **فجوات التغطية (Coverage gaps):** negative heatmap of underserved cells.
- **تحسين البيانات (Data Quality / Improvement Mode):** Flags mapping issues on the map, helping contributors identify and correct errors. It checks for:
  1. **Missing Amenity tag**: `building=mosque` without `amenity=place_of_worship`.
  2. **Generic Name**: Empty name or default placeholder (e.g., "مسجد" or "Mosque").
  3. **Missing English Translation**: Missing `name:en` or identical to Arabic.
  4. **Missing Denomination**: Muslim mosques with unspecified sect/denomination.
  5. **Missing Wheelchair accessibility**: Accessibility tags are unknown or missing.
  6. **Generic Building Tag (`building=yes`)**: Mosque building tagged as `building=yes` instead of `building=mosque`.
- **محرر OSM المدمج (OSM Editor Integration):**
  - Integrated OpenStreetMap authentication via OAuth 2.0 (supports production and development environment logins) to verify user accounts.
  - Direct integration with **iD Editor (Web)** to edit the current map view area.
  - Direct integration with **JOSM** via remote control port (8111) to load and zoom to specific nodes/ways for immediate tagging fixes.
- **مؤشر اتجاه القبلة (Qibla Compass):** An overlay tool displaying a Qibla compass pointer in the center of the map to verify mosque orientation.
- Adjustable heatmap radius/blur, live in-viewport counts.
