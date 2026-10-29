# Manara: ideas from the openstreetmap GitHub org

## Context
You asked me to read https://github.com/orgs/openstreetmap/repositories (90 repos, 3 pages) and turn what the best OSM projects do into improvements for Manara. Most of the org is infrastructure (chef, dns, mod_tile, tirex, osmdbt, cgimap) or archived conference sites, so it has little to teach a client app. The repos that do matter are:

- **iD** (editor)
- **id-tagging-schema** (presets, fields, deprecations)
- **software-roadmap** (OSMF direction)
- **vectortile-website** (Shortbread/MapLibre demo)
- **leaflet-osm** (data-layer plugin)
- **OSM-binary** (PBF)
- **osmdbt** and the minutely diffs (replication model)
- **tile-attribution** and the OSMF policies on tiles and the API

I checked each idea against your memory rules: Geofabrik public extract only, no bulk API reads, per-object reads only from the user's browser, and a small VPS (pipeline capped at 1.5 GiB).

Manara today: vanilla JS, Leaflet and Vite. FastAPI, PostGIS and a pipeline. About 14k places and 54k suggestions shipped as static GeoJSON. Editing is done through four tag-only quick fixes and an add-mosque modal.

## Recommended ideas, in priority order

### 1. Preset and field schema for mosque editing (from id-tagging-schema)
- **Problem:** tag validation is ad hoc. `editing.js` has `QUICK_FIXES` plus hand-written checks in `osm_api.js` and `app.js`. This is the biggest gap against iD.
- **Idea:** define a small declarative mosque preset in the iD style. It holds the fields, `addTags`, `removeTags` and `moreFields`. Fields would be denomination (combo), `female:prayer_room` (check), `wheelchair`, `name:ar`, `name:en`, `wikidata`, `capacity` and `opening_hours`. The add modal and quick fixes would render from it.
- **Also take:** `deprecated.json`-style upgrade rules, for example `building=yes` to `building=mosque`, or `religion=islam` to `muslim`.
- **Reuse:** the `@openstreetmap/id-tagging-schema` npm package (`dist/presets.json`) as a build-time source of truth. Fetch it in the Vite build and keep only the place_of_worship/mosque subset, not the whole 1 MB file.
- **Files:** `frontend/src/editing.js`, the add-mosque code in `frontend/src/app.js` (~L3180-3465), and a new `frontend/src/presets.js`.
- **Compliance:** no OSM API calls, so no impact.

### 2. A validator layer before upload (from iD's `coreValidator`)
- **Idea:** rule functions that return `error` (blocks upload) or `warning` (can be ignored), as iD does. Candidate rules:
  - Duplicate or nearby mosque within about 50 m, with a name-similarity check. This is missing from add-mosque today.
  - Point outside the Saudi boundary.
  - Missing `religion`.
  - Mismatch between `name` and `name:ar`.
  - Denomination typos.
- **Also take:** iD records counts of ignored warnings and resolved issues in changeset tags. Manara could add `manara:warnings_ignored` for reviewers.
- **Data source:** the duplicate check runs against the already-loaded `places` dataset, or the backend's `/api/v1/search` and bbox, never the OSM API.
- **Files:** new `frontend/src/validator.js`, called from `createNode`/`addNode` and `applyEdits()`.
- **Tests:** these are pure functions, so they are easy to unit test. Add Vitest for the frontend. It's missing today.

### 3. Immutable edit state, undo and a diff (from iD's graph and history)
- **Idea:** replace the in-memory dataset patching ("add the new feature to local datasets right away") with a small overlay of pending edits. Each edit is a new immutable state, so you get undo/redo and a draw-only-the-difference (`coreDifference`) update of the map.
- **Why:** it makes the "removed added markers" and "exclude resolved suggestions" fixes in your recent commits structural instead of patched. `EditHistory` in `localStorage` already holds 300 entries and could become the persistence layer.
- **Option:** an iD-style restore prompt, so a half-finished batch survives a page reload.
- **Files:** `frontend/src/osm_api.js` (`EditHistory`), `editing.js`.

### 4. Faster loading: spatial index and bbox loading (from iD's `coreTree` / rbush)
- **Problem:** the browser downloads about 7.5 MB of places and 11 MB of suggestions as JSON, and `app.js` is one 3.4k-line file. Your own roadmap names this as a mobile bottleneck.
- **Quick win:** switch the frontend to the existing `/api/v1/suggestions?bbox=` endpoint. `HANDOFF.md` lists this as optional, but it is already built.
- **Next:** build the dataset as FlatGeobuf or Protobuf (see OSM-binary for the idea of compact binary over JSON), or as vector tiles (idea 5). Use `rbush` client-side for hit-testing and viewport queries.
- **Also:** split `app.js` along iD's modes/behaviors idea (browse, select, add, review), which keeps each interaction state's listeners in one place with `enter` and `exit`.
- **Memory:** the API container is capped at 256 MiB. bbox queries over PostGIS with a GiST index are cheap, but test under that cap.

### 5. Self-hosted vector tiles as a static PMTiles file (from vectortile-website / software-roadmap)
- **Why:** the OSMF roadmap is moving to MapLibre and Shortbread vector tiles. The OSMF vector tile policy forbids bulk downloads and offline packs and warns that donation-seeking services are the first to lose access. So do not use OSMF's tiles, and keep avoiding `tile.openstreetmap.org`.
- **Idea:** generate a Shortbread-schema `.pmtiles` for the GCC from the same Geofabrik extract with Planetiler, and serve it as a static file from Caddy using HTTP range requests. That gives dark mode, Arabic labels (`name:ar`) and a place layer in one file, with no tile server.
- **Constraint:** Planetiler can exceed the 1.5 GiB pipeline cap. Build it in GitHub Actions on a schedule and publish it as a release asset, or skip this idea.
- **Cost:** it means moving Leaflet to MapLibre GL, which is a large change. Treat it as a later phase. It also lets you put places, gaps and suggestions into vector tiles, which removes idea 4's JSON problem altogether. This matches the "vector tiles" item in your `NEXT_LEVEL_ROADMAP.md`.

### 6. Accessibility and RTL pass (from iD's ACCESSIBILITY.md)
- iD documents its gaps openly. Do the same: add an `ACCESSIBILITY.md` to Manara listing known gaps.
- Concrete items:
  - Focus trap in modals and restore focus on close.
  - Keyboard access to map features (iD's own known gap, so doing it well would be ahead of iD).
  - `aria-live` announcements for save, conflict and error states.
  - Don't rely on colour alone (gap heat map, review status).
  - Replace hardcoded inline colours, for example in the add-mosque auth block, with tokens that work in dark mode.
- Also take from iD: a connection-lost banner with automatic retry, since users in the field have poor signal.

### 7. Offline-tolerant "Manara Field" PWA (from iD's gap, StreetComplete's idea)
- iD says offline is unsupported, so this is a differentiator. Add a service worker and manifest, cache the app shell and `summary.json`, and queue pending edits in IndexedDB until the connection returns.
- Compliance: only your own static files are cached. Edits are replayed one by one through the existing conflict-checked `applyEdits()`. There is no OSM tile or API prefetching.

### 8. StreetComplete-style resurvey questions
- StreetComplete shows the current value and asks whether it is still correct, and skips values that rarely change (like 24/7).
- For mosques: ask "is this mosque still open?", "is there a women's prayer room?", "what is the denomination?", "wheelchair access?" one at a time on mobile. This extends your four `QUICK_FIXES` into a question queue ordered by gap priority.
- Also record `check_date` when a user confirms an unchanged value (an OSM convention). Do not write an unchanged value back as a change; your batch code already skips unchanged edits.

### 9. Documentation and housekeeping
- Add machine-readable API docs. FastAPI already generates OpenAPI, so expose `/api/docs`. The OSM roadmap lists this as a developer-experience goal.
- Add a short "data model and policies" page: where the data comes from (public Geofabrik extract plus daily diffs), how it is licensed (ODbL), and the compliance rules. This also helps OSM community members trust the project.
- Attribution: confirm the OSM contributors credit is visible bottom-right on every map page, per OSMF policy.
- Frontend tests: none today. Start with `osm_api.js` changeset and conflict logic, since an error there writes bad data to OSM.

## Things noticed in the repo (not from OSM, worth fixing)
- `cert.pem` and `key.pem` sit in the repo root. They are gitignored but present on disk. Delete them if they are not needed.
- A DB password was committed in `1450983`. It was rotated, but it is still in git history.
- The OAuth access token is kept in `localStorage`. Idea: keep it in memory only (or `sessionStorage`) and rely on the `__Host-` session cookie.
- `transliteration.py` is duplicated between `backend/app/` and `pipeline/`. Share one module.
- `HANDOFF.md` has stale image pins (says `node:22-alpine`/`alpine:3.22`, Dockerfile has `node:26-alpine`/`alpine:3.24`).

## Suggested order
1. Ideas 1 and 2: preset schema plus validator. Highest value for data quality, small, no infrastructure.
2. Idea 4 quick win (bbox loading), then the repo housekeeping above.
3. Ideas 6 and 8: accessibility and the question-queue UI.
4. Ideas 3 and 7: edit state and the offline PWA.
5. Idea 5: vector tiles, only once the above is stable.

## Verification (once any idea is implemented)
- `pytest` for backend and pipeline, plus the new Vitest suite for validator and preset code.
- `npm run lint` and `npm run build` in `frontend/`.
- Run the app and test the add-mosque and quick-fix flows against the OSM **dev** server (`master.apis.dev.openstreetmap.org`), which `osm_api.js` already supports. Do not test edits on the live OSM server.
- Check the browser network tab: no requests to `tile.openstreetmap.org` and none to `api.openstreetmap.org` except per-object reads and edits on user action.
- Measure initial page weight before and after idea 4.
