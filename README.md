# خارطة الكثافة وفجوات التغطية لأماكن العبادة — Saudi Places of Worship Map

An interactive, offline-processed map of places of worship across Saudi Arabia,
plus a "coverage gaps" analysis highlighting inhabited grid cells (by road
density) that contain **zero** places of worship, and a data-improvement mode
for finding and fixing OpenStreetMap tagging problems.

The front-end is a Leaflet dashboard (Arabic RTL by default, with an English
toggle) built with Vite and served from a VPS (Coolify) by Caddy. All heavy data
processing happens ahead of time in Python from an OpenStreetMap `.pbf`
extract.

Live site: <https://manara.saudiosm.org>

## Contents

| File | Purpose |
|------|---------|
| [common.py](common.py) | Shared pipeline helpers: PBF lookup, centroids, Arabic name normalization, atomic JSON writes, `summary.json`. |
| [extract_sa_boundary.py](extract_sa_boundary.py) | Builds the Saudi Arabia boundary polygon from OSM. |
| [extract_places.py](extract_places.py) | Extracts places of worship (nodes, ways and multipolygon relations) inside the boundary, merging POI nodes into the building outline they sit in. |
| [calculate_gaps.py](calculate_gaps.py) | Grids the country and flags road-populated cells far from any place of worship. |
| [calculate_mosque_sizes.py](calculate_mosque_sizes.py) | Footprint area of every mosque outline (size outliers are judged in the browser). |
| [detect_geometry_anomalies.py](detect_geometry_anomalies.py) | Isolation Forest model flagging distorted / over-noded outlines, plus each building's Qibla deviation. |
| [import_wikidata_suggestions.py](import_wikidata_suggestions.py) | Wikidata mosques missing from OSM, from the [osm x wikidata](https://github.com/Abdullah201x/osm-x-wikidata) project's `data/sa.json`. |
| [validate_data.py](validate_data.py) | Blocks publishing when a dataset is missing, unreadable, or shrank by more than 20%. |
| [frontend/](frontend) | The Vite app: `index.html` (the map), `about.html`, `privacy.html`. |
| [frontend/src/](frontend/src) | ES modules: `main.js` (entry), `app.js` (the dashboard), `i18n.js` + `translations*.js` (Arabic/English), `arabic.js` (name normalization), `review.js` (review queue, marks, permalinks, shortcuts), `exporters.js` (CSV, MapRoulette, JOSM, Overpass), `osm_api.js` (OAuth + API 0.6 editing), `editing.js` (quick fixes, batch, history), `analytics.js` (Umami), `vendor/` (pinned Leaflet.BoundaryCanvas). |
| [Dockerfile](Dockerfile) / [deploy/Caddyfile.container](deploy/Caddyfile.container) | The production image (Coolify Dockerfile build pack): frontend build, datasets precompressed at build time, served by Caddy with the security headers, CSP, caching rules and the `/stats` proxy to Umami. |
| [tests/](tests) | pytest tests for the shared helpers. |
| [ML_ROADMAP.md](ML_ROADMAP.md) | Machine learning roadmap (Arabic). |

Generated data (committed, consumed by the front-end):

| File | Contents |
|------|----------|
| `summary.json` | Counts per dataset, the OSM extract date, and `updated_at` (used by the front-end as the cache version). |
| `places_of_worship_sa.geojson` | One point per place of worship. |
| `worship_gaps_sa.json` | Compact gap grid: `{grid_size, cells: [[gx, gy, road_length_m, gap_score], ...]}`. |
| `mosque_sizes.json`, `mosque_anomalies.json` | Per-way footprint area / ML anomaly scores and Qibla deviation. |
| `suggested_mosques_sa.geojson` | Wikidata suggestions layer. |
| `sa_boundary.geojson` | Country boundary. |

## Prerequisites

- Python 3.9+
- `pip install -r requirements.txt`
- An OSM `.pbf` extract covering Saudi Arabia (e.g. Geofabrik's GCC states).
  The scripts look for it in `$OSM_PBF`, then this folder, then the sibling
  `../update osm` folder used by the master updater; the newest `*.pbf` wins.

## Data pipeline

Run the scripts **in this order** (each reads the previous step's output):

```bash
python extract_sa_boundary.py          # -> sa_boundary.geojson
python extract_places.py               # -> places_of_worship_sa.geojson
python calculate_gaps.py               # -> worship_gaps_sa.json
python calculate_mosque_sizes.py       # -> mosque_sizes.json
python detect_geometry_anomalies.py    # -> mosque_anomalies.json
python import_wikidata_suggestions.py  # -> suggested_mosques_sa.geojson (reads osm x wikidata data/sa.json)
python validate_data.py                # exits non-zero if anything looks wrong
```

Every script writes minified JSON atomically and records its counts in
`summary.json`. In day-to-day use the master updater
(`../update osm/update_projects.py`) downloads the extract, runs all of the
above, and commits only the generated data files when validation passes.

Tests: `pytest`.

Notes:
- The Saudi Arabia boundary uses OSM relation id **307584**.
- A tagged POI node inside a mosque building outline is merged into that
  building (the building keeps its geometry, the node's name/amenity/religion
  fill in). When both carry `amenity=place_of_worship` the place gets a
  "mapped twice" issue.
- The gap grid uses ~0.004° cells (~440 m, close to typical neighborhood
  mosque spacing). A cell is a candidate when it contains at least 2 distinct
  drivable ways, and a gap when the nearest place of worship (STRtree query)
  is more than 750 m away. Gap intensity scales with that distance and with
  the cell's drivable road **length** (through-traffic classes downweighted),
  which, unlike a way count, isn't inflated by OSM splitting ways at every tag
  change.
- The ML anomaly flag is the Isolation Forest verdict only; Qibla deviation is
  a separate check with its own (adjustable) threshold.

## Running the front-end

Requires Node.js 20+.

```bash
cd frontend
npm install
npm run dev        # https://localhost:8000/ with hot reload
npm run build      # production build in frontend/dist
npm run preview    # serves the build with the production CSP header
npm run lint
```

The dev server uses a self-signed certificate (accept it on first visit),
because OpenStreetMap OAuth only accepts HTTPS redirect URIs. Datasets are
served under `/data/` from the repo root, or from `MANARA_DATA_DIR` if set;
only the known dataset names are served.

## Deployment (VPS)

The VPS runs Coolify, whose Traefik proxy owns ports 80/443 and terminates
TLS. Manara is a Coolify application using the **Dockerfile** build pack on
the root [Dockerfile](Dockerfile); pushes to `main` redeploy it. Inside the
container Caddy listens on port 80 and:

- serves the built frontend and the datasets from precompressed `.br`/`.gz`
  copies made at build time;
- adds the security headers and the Content-Security-Policy (the same line is
  read by `npm run preview`);
- proxies `/stats/*` to the shared Umami instance
  (`analytics.rahmahealth.net`, where Manara is its own website), passing the
  visitor IP in `CF-Connecting-IP` so country stats stay correct.

The Umami website ID is the `VITE_UMAMI_WEBSITE_ID` build argument (default in
the Dockerfile).

The old GitHub Pages address keeps working: there is no root `index.html` and
`.nojekyll` stops Jekyll from rendering this README in its place, so Pages
serves `404.html` for every path, which redirects to `manara.saudiosm.org`.

### OSM login

Login uses OAuth 2.0 with PKCE. Set `DEFAULT_OSM_CLIENT_ID` in
[frontend/src/osm_api.js](frontend/src/osm_api.js) to the client ID of an application registered
on openstreetmap.org with the redirect URI
`https://manara.saudiosm.org/` (and
`https://localhost:8000/` for local testing), as a public (non-confidential)
client with the scopes *Read user preferences*, *Modify the map* and *Create
notes*. Until then, or for a self-hosted copy, a client ID can be entered in
the login dialog under "advanced settings".

## Front-end features

- **كثافة الأماكن (POI density):** heatmap + clustered markers, filterable by
  religion and last-edit date. Search ignores diacritics and spelling variants
  (أ/ا, ة/ه, ى/ي) and treats جامع and مسجد as the same word.
- **فجوات التغطية (Coverage gaps):** continuous gradient of underserved cells,
  with buttons to open the current view in iD or JOSM to add a mosque.
- **تحسين البيانات (Data improvement):** flags mapping issues:
  1. **Missing amenity tag:** `building=mosque` without `amenity=place_of_worship`.
  2. **Generic name:** empty, or only generic words ("مسجد", "الجامع", "مصلى", "Mosque", numbers).
  3. **Missing English name:** no `name:en`, or identical to the Arabic name.
  4. **Missing denomination** for Muslim places of worship.
  5. **Unusual building size** (adjustable limits).
  6. **Stale data:** still `version=1` after 5+ years.
  7. **`building=yes`** on a mosque instead of `building=mosque`.
  8. **Mapped as a node** instead of a building outline.
  9. **ML geometry anomaly** (Isolation Forest).
  10. **Qibla misalignment:** building axis deviating from the great-circle
      bearing to the Kaaba by at least an adjustable threshold (default 20°).
  11. **Mapped twice:** building and a point inside it both tagged as the place of worship.
- **Review workflow:**
  - `N` / `P` step through the current list (the Qibla list by severity,
    everything else nearest-first from the map view).
  - Mark places *fixed* (`F`) or *skipped* (`S`); marked places are hidden and
    left out of the counts until newer OSM data arrives.
  - Optional "visible area only" issue counts.
  - Keyboard shortcuts (`?` lists them).
- **Permalinks:** the URL keeps the mode, issue filter, religion filter,
  search, map view, selected place and language, so a view can be shared.
- **Exports of the current list:** CSV (UTF-8 BOM, opens correctly in Excel),
  MapRoulette challenge GeoJSON with per-task instructions, loading the
  visible places into JOSM, and an Overpass Turbo query for tag-based checks.
- **In-app fixes (OSM API 0.6):** after logging in, tag-based issues (missing
  amenity, `building=yes`, missing `name:en`, missing denomination) can be
  fixed from the details panel. Every edit shows the tag diff and an editable
  changeset comment and source, checks that the object hasn't changed since
  the data was published, and uploads in a changeset that is always closed.
  Individually reviewed fixes can be queued and uploaded together in one
  changeset; there is no bulk "fix all". A local "My edits" history keeps the
  changesets made from this browser (CSV/JSON export).
- **JOSM / iD integration:** open any place in iD, or load and select it
  (building and merged POI node) in JOSM via Remote Control.
- **مؤشر اتجاه القبلة (Qibla compass)** overlay at the map centre.
- **ملاحظات OSM (OSM Notes):** add notes from the map, signed in or
  anonymously, with presets (missing place of worship, fixme, place is gone);
  every note is signed `via خارطة أماكن العبادة (...) #sa-worship-map`.
- **Basemaps:** keyless Esri dark/light/streets/satellite (satellite clipped to
  the country, with automatic maximum-zoom discovery), or CARTO with a free key.
- **اقتراحات ويكي بيانات (Wikidata suggestions):** Wikidata mosques more than
  100 m from any OSM place of worship, with cleaned names, non-mosque and
  landform false positives removed, satellite preview, tag copy, and one-click
  add in iD or JOSM.
- **العربية / English:** the whole interface switches language and direction.
