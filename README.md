# خارطة الكثافة وفجوات التغطية لأماكن العبادة — Saudi Places of Worship Map

An interactive, offline-processed map of places of worship across Saudi Arabia,
plus a "coverage gaps" analysis highlighting inhabited grid cells (by road
density) that contain **zero** places of worship.

The front-end is a static Leaflet dashboard (Arabic, RTL). All heavy data
processing happens ahead of time in Python from an OpenStreetMap `.pbf` extract.

## Contents

| File | Purpose |
|------|---------|
| `extract_sa_boundary.py` | Builds the Saudi Arabia boundary polygon from OSM. |
| `extract_places.py` | Extracts all `amenity=place_of_worship` features inside the boundary. |
| `calculate_gaps.py` | Grids the country and flags road-populated cells with no worship place. |
| `index.html` / `app.js` / `index.css` | The Leaflet dashboard front-end. |
| `*.geojson` | Generated data consumed by the front-end. |

## Prerequisites

- Python 3.9+
- Python packages:

  ```bash
  pip install osmium shapely
  ```

- An OSM `.pbf` extract covering Saudi Arabia, saved in this folder as
  `gcc-states-260709-internal.osm.pbf` (e.g. a GCC-states extract from Geofabrik).

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
  (`extract_sa_boundary.py`).
- The gap grid uses ~0.02° cells (~2.2 km) and treats a cell as a "gap" when it
  has enough drivable-road segments but no places of worship
  (`calculate_gaps.py`).

## Running the front-end

The app loads GeoJSON via `fetch`, which requires HTTP (it will **not** work by
opening `index.html` directly over `file://`). Serve the folder locally:

```bash
python -m http.server 8000
```

Then open <http://localhost:8000/> in a browser.

## Front-end features

- **كثافة الأماكن (POI density):** heatmap + clustered markers, filterable by
  religion, searchable by name/city/OSM id.
- **فجوات التغطية (Coverage gaps):** negative heatmap of underserved cells.
- Adjustable heatmap radius/blur, live in-viewport counts.
