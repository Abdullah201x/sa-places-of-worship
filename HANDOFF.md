# Manara (manara.saudiosm.org): Project Handoff

This document summarises the architecture, live infrastructure, completed phases (Phases 1–3), and upcoming roadmap (Phases 4–6) for **Manara** (`https://manara.saudiosm.org`), so another AI coding assistant can seamlessly continue the work.

- **Last updated:** 2026-10-28
- **Repository:** `github.com/Abdullah201x/sa-places-of-worship` (branch `main` auto-deploys via Coolify)
- **Local checkout:** `C:\Users\abdul\Desktop\GCC20260707`
- **VPS SSH:** `root@159.195.192.148`

---

## 1. What the Project Is

Manara is an interactive Leaflet map of places of worship in Saudi Arabia, built from OpenStreetMap data. The UI is Arabic (RTL) by default, with an English toggle. It has three modes:
- **POI density** (clustering + heatmap);
- **Coverage gaps** (road-network grid cells lacking nearby mosques);
- **Data-improvement mode for mappers**: issue detection, a review queue, Wikidata suggestions (~54.5k missing mosques), exports (GeoJSON, CSV, KML, OSM XML, MapRoulette), and in-app tag fixes through the OSM API with OAuth2 PKCE.

A daily server-side Python pipeline (`pipeline/`, using `osmium`, `shapely`, `scikit-learn`, `psycopg`) turns Geofabrik's public GCC `.pbf` extract into static compressed JSON/GeoJSON datasets **and** loads them atomically into a PostGIS 17 database backing a public read-only FastAPI service (`backend/`).

| Dataset File | Records | Contents |
|---|---|---|
| `summary.json` | — | Counts, `updated_at` (also the frontend's cache-busting `?v=` token), `pbf_date` |
| `places_of_worship_sa.geojson` | ~14,021 | OSM places of worship (`node`, `way`, `relation` centroids + tags, `version`, `edited_at`) |
| `worship_gaps_sa.json` | ~59,695 | Road-network gap grid cells (`[grid_x, grid_y, road_length_m, gap_score]`) |
| `sa_boundary.geojson` | 1 | Saudi Arabia national boundary (`ISO3166-1=SA`, `admin_level=2`) |
| `sa_regions.geojson` | 13 | All 13 Saudi administrative provinces (`SA-01` to `SA-14`, `admin_level=4`) |
| `mosque_sizes.json` | ~5,686 | Building footprint areas (`{osm_id: {"area_m2": float}}`) |
| `mosque_anomalies.json` | ~5,686 | IsolationForest anomaly scores (`is_anomaly`, `anomaly_score`) and Qibla deviation (`qibla_dev`) |
| `suggested_mosques_sa.geojson` | ~54,504 | Wikidata mosques >100 m from any OSM place of worship (`qid`, `name_ar`, `name_en`, `nearest_osm_m`, `is_unnamed`) |

---

## 2. Hard Constraints (MUST RESPECT)

### VPS & Coolify Topology
See `VPS_HARDWARE_ANALYSIS.md`.
- **Hardware:** 2 vCPU (AMD EPYC Genoa), 3.8 GiB RAM (~2.2 GiB available with all 4 Manara containers running), 2 GiB swap, 106 GiB free disk, Debian 13.
- **Orchestrator:** **Coolify 4.5**. **Traefik (`coolify-proxy`) owns host ports 80/443**. There is no host Caddy or nginx. Never bind host ports 80/443.
- **Neighboring services:** The VPS also hosts **rahmahealth.net** (`nn0yw94zrb6w7lbgpmzt3jko`). **Never touch Rahma's containers.**
- **Shared Analytics:** Keep Manara completely isolated from Rahma, with the single user-approved exception that Manara uses the **shared Umami** instance (v3.0.3, `analytics.rahmahealth.net`) as its own website, ID `401cdcc1-cbfb-4962-8fc7-9d906f900bff`.

### Live Coolify Resources (on Docker network `coolify`)

| Service | Coolify UUID / Container Prefix | Image / Build | Port | Memory Cap | Actual RAM | Notes |
|---|---|---|---|---|---|---|
| **Web (Caddy + SPA)** | `qri8jmjjfbuaiwyfwbunrjvn` | Root `Dockerfile` | `:80` | — | ~15 MiB | Public domain `https://manara.saudiosm.org`; mounts `/data/manara/published:/srv/manara/published:ro` |
| **Pipeline Worker** | `e3xakpyxk2xmq19aqpyvjdjq` (`manara-pipeline`) | `pipeline/Dockerfile` | None | `1.5 GiB` (`1.5 CPU`) | ~17 MiB idle (~970 MiB peak) | Runs `python run.py schedule` (daily 23:30 UTC / 02:30 Riyadh); mounts volume `manara-state:/state` and host `/data/manara/published:/published` |
| **FastAPI Backend** | `mp6ebt0ybcqvpmk4bke8d56w` (`manara-api`) | `backend/Dockerfile` | `:8010` | `256 MiB` | ~45 MiB | Consistent container name enabled; Docker network alias `manara-api` on `coolify` network; proxied by Caddy `handle /api/*` |
| **PostGIS Database** | `9uzoip4gqaxybg3e5oymh8sg` (`manara-db`) | `postgis/postgis:17-3.5-alpine` | `:5432` | `512 MiB` | ~241 MiB | Database `manara`, user `manara`, extensions `postgis` and `pg_trgm` enabled |

- **Internal `MANARA_DATABASE_URL`** (configured on both `manara-pipeline` and `manara-api`):
  ```text
  postgresql://manara:ZXhAu4Iw2PB5XQauQhAP54AjMe0Yk0vPnNhRPB8ymMl7AnEfH5puAgVLCjrslJqx@9uzoip4gqaxybg3e5oymh8sg:5432/manara
  ```

### OSM Compliance (Strict Requirement)
- **No bulk reads from `api.openstreetmap.org`, ever.**
- Bulk data comes only from **Geofabrik's public** GCC extract (`https://download.geofabrik.de/asia/gcc-states-latest.osm.pbf`):
  - downloaded **once** to `/state/gcc-states.osm.pbf`;
  - kept current with Geofabrik's **daily diffs** using `pyosmium-up-to-date`.
- The public extract drops `user`, `uid`, and `changeset`, but keeps `version` and `timestamp`.
  - The app only uses the dropped fields for the "last edited by / UID / changeset" rows in the details panel (`frontend/src/app.js`).
  - Those rows are **fetched lazily**: one `GET /api/0.6/{type}/{id}.json` from the **user's own browser** (`OsmApi.fetchLastEdit` in `frontend/src/osm_api.js`), only when a logged-in mapper opens a place, cached in `sessionStorage` by `osm_meta:${type}/${id}@${version}`. Guests see a GDPR notice and make zero OSM API calls.
- Server-side OSM writes (Phase 4) must:
  - send User-Agent `Manara/1.0 (+https://manara.saudiosm.org)`;
  - respect 429 `Retry-After`;
  - apply per-user limits (~10 changesets/hour, max 50 objects/changeset);
  - always close changesets;
  - never offer a "fix all" button.
- Map tiles come from Esri and CARTO only, never `tile.openstreetmap.org`.

---

## 3. Phase 1: DONE & Live (Vite Frontend + Caddy Container)

### Frontend (`frontend/`)
- **Vite MPA**:
  - `index.html` (map), `about.html`, `privacy.html` (bilingual `[data-lang]` blocks with shared i18n module).
  - ES modules in `frontend/src/`: `main.js`, `app.js`, `i18n.js`, `translations*.js`, `arabic.js`, `review.js`, `exporters.js`, `osm_api.js`, `editing.js`, `analytics.js`, `page.js`, `leaflet-setup.js`.
  - Self-hosted dependencies (Leaflet, markercluster, leaflet.heat, `@fontsource-variable/*`). No CDN, no Google Fonts.
- **Two build gotchas in `frontend/vite.config.js` (keep intact):**
  - `cssMinify: 'esbuild'`: Lightning CSS drops unprefixed `backdrop-filter` with `var()`, breaking glass blur in Chrome.
  - `assetsInlineLimit` never inlines `.woff2` files because CSP enforces `font-src 'self'`.
- **Umami (`frontend/src/analytics.js`):**
  - Loaded via `/stats/script.js` with `data-host-url="/stats"`. Only `/stats/script.js` and `/stats/api/send` are proxied by Caddy to `https://analytics.rahmahealth.net`; `/stats/login` returns 404.

---

## 4. Phase 2: DONE & Live (Server-Side Daily Pipeline)

1. **GDPR-clean extraction (`pipeline/extract_places.py`):**
   - Removed `last_edited_by`, `user_id`, and `changeset_id` from `places_of_worship_sa.geojson`. Kept `version` and `edited_at`.
2. **In-browser lazy contributor fetch (`frontend/src/osm_api.js` & `frontend/src/app.js`):**
   - `OsmApi.fetchLastEdit(type, id, version)` fetches `/api/0.6/{type}/{id}.json` only for logged-in mappers when inspecting a single place, with race-condition guards and `sessionStorage` caching.
3. **Automated daily runner (`pipeline/run.py` & `pipeline/Dockerfile`):**
   - Runs `python run.py schedule` (daily at `23:30` UTC).
   - Updates `/state/gcc-states.osm.pbf` via `pyosmium-up-to-date`, checks `osmosis_replication_sequence_number`, fetches Wikidata `sa.json` with ETag caching, runs all pipeline steps in `/state/work`, pre-compresses `.br` and `.gz`, publishes to `/published/v<TIMESTAMP>`, atomically swaps relative symlink `current -> v<TIMESTAMP>`, and retains the 2 most recent versions.
4. **Live dynamic `/data/*` serving (`deploy/Caddyfile.container`):**
   - Serves from `/srv/manara/published/current` when present, falling back to baked `/srv/manara/data`.
5. **Desktop updater retired:**
   - Removed `"gcc"` entry from `C:\Users\abdul\Desktop\update osm\update_projects.py`.

---

## 5. Phase 3: Backend & PostGIS DONE & Live (Frontend Wiring Optional/Next)

### Completed & Verified Live on `https://manara.saudiosm.org`
1. **Saudi Regions Extractor (`pipeline/extract_regions.py` + `tests/test_extract_regions.py`):**
   - Extracts all 13 Saudi administrative provinces (`ISO3166-2` `SA-01` through `SA-14`, `admin_level=4`) from the PBF into `sa_regions.geojson` (all 1,479 boundary ways resolved, 100% valid polygons).
2. **PostGIS Atomic Loader (`pipeline/load_db.py`):**
   - Runs as the final step of `pipeline/run.py` whenever `MANARA_DATABASE_URL` (or `DATABASE_URL`) is set (exits cleanly with 0 when unset).
   - Creates `postgis` and `pg_trgm` extensions and production schema (`regions`, `places`, `gaps`, `suggestions`, `dataset_versions`, `region_stats_history`).
   - Bulk-loads staging tables via PostgreSQL `COPY`, maps `Point`/`Polygon`/`Relation` to OSM types `node`/`way`/`relation`, assigns `region_code` spatially via `ST_Within(geom, regions.geom)`, records regional history snapshots using CTE aggregations (avoiding multi-table Cartesian joins), and swaps staging tables into production in a single atomic transaction (~9–14s total runtime).
3. **FastAPI Geospatial Data Service (`backend/` + `tests/test_backend_api.py`):**
   - Deployed as `manara-api` on port `8010`, proxied by Caddy via `handle /api/*` (`{$MANARA_API_URL:http://manara-api:8010}`).
   - Rate-limited with `slowapi` (`120/minute`), connection-pooled with `psycopg_pool`, and tested in CI (`.github/workflows/ci.yml` runs all 42 pytest unit tests + frontend lint & build).
   - **Live Endpoints:**
     - `GET /api/healthz` -> `{"status":"ok"}`
     - `GET /api/v1/meta` -> active dataset version (`v20261028T001156Z`), `pbf_date`, counts, and `summary.json` metadata.
     - `GET /api/v1/stats` -> overall counts (`total_places: 14021`, `muslim_places: 13999`, `anomaly_places: 86`, `qibla_deviated_places: 605`, `total_gaps: 59695`, `total_suggestions: 54504`, `total_regions: 13`).
     - `GET /api/v1/stats/regions` -> per-province breakdown (`SA-01`..`SA-14`) of places, gaps, suggestions, anomalies (`anomaly_score < 0`), and Qibla deviations (`qibla_dev >= 20°`).
     - `GET /api/v1/stats/history?region=SA-01&limit=50` -> time-series snapshots from `region_stats_history`.
     - `GET /api/v1/places/{type}/{id}` -> single place GeoJSON Feature (`type` in `node|way|relation`) with province name (`region_code`, `region_name`, `region_name_en`), footprint area, anomaly score, and Qibla deviation.
     - `GET /api/v1/suggestions?bbox=minLon,minLat,maxLon,maxLat&limit=100` -> GiST spatial bounding-box query (max span `3.0°`, limit `1..500`). Returns GeoJSON FeatureCollection with properties `{qid, wikidata_id, name, name_ar, name_en, nearest_osm_m, is_unnamed, region_code}` matching `buildSuggestionPopup` in `frontend/src/app.js`.
     - `GET /api/v1/search?q=<query>&limit=20` -> Arabic-normalized (`normalize_arabic`) `pg_trgm` trigram similarity + English `ILIKE` search across places.
     - `GET /api/docs` -> OpenAPI / Swagger UI.

### Optional Frontend Enhancement (Remaining from Phase 3)
- Currently, `frontend/src/app.js` still downloads the static `/data/suggested_mosques_sa.geojson` (1.1 MB Brotli / 10.9 MB raw, 54,504 features) when the user toggles Suggestions mode.
- Now that `GET /api/v1/suggestions?bbox=...` is live and returns the exact property structure expected by `buildSuggestionPopup` (`qid`, `name_ar`, `name_en`, `nearest_osm_m`, `is_unnamed`, `region_code`), the frontend can optionally be updated to fetch suggestions dynamically by viewport bbox on `moveend` (or keep the static pre-compressed bundle if client-side instant filtering/clustering of all 54k points is preferred).

### Phase 2 & 3 Commits on `main`
| Commit | Content |
|---|---|
| `9380707` | Phase 2 pipeline container, GDPR property cleanup, lazy contributor fetch, `extract_regions.py` |
| `5e8ef9c` | Phase 3 FastAPI backend (`backend/`), PostGIS loader (`pipeline/load_db.py`), Caddy `/api/*` proxy, API unit tests |
| `96243b7` | Fix staging `COPY` explicit IDs, dict extraction for `mosque_sizes.json`, and CTE optimization for `region_stats_history` |
| `20aec39` | Install backend deps in GitHub Actions CI, map `osm_type` (`node`/`way`/`relation`), and use `anomaly_score < 0` in stats |

---

## 6. Phase 4: Next Up — Accounts & Shared Review

- **Server-side OSM OAuth2:**
  - Register a confidential OAuth2 app on `openstreetmap.org` (and `master.apis.dev.openstreetmap.org` for testing) with redirect URI `https://manara.saudiosm.org/auth/callback` and scopes `read_prefs write_api write_notes`.
  - Endpoints in `backend/app/routers/auth.py`: `GET /auth/login`, `GET /auth/callback` (code + PKCE + state), `POST /auth/logout`, `GET /api/v1/me`.
  - Note: also add `handle /auth/*` to `deploy/Caddyfile.container` (proxying to `{$MANARA_API_URL:http://manara-api:8010}`, matching `frontend/vite.config.js` which already proxies `/auth`).
- **Identity & Security:**
  - Identity (`osm_uid`, `display_name`, `avatar_url`) must come **only** from server-side `GET /api/0.6/user/details.json` using the OAuth token — never from client input.
  - Store OAuth access tokens **Fernet-encrypted** (`MANARA_FERNET_KEY`) in a `sessions` table.
  - Set session cookie `__Host-manara_session` (`HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`).
  - Require `Origin: https://manara.saudiosm.org` and custom header `X-Manara-CSRF: 1` on every `POST`/`PUT`/`DELETE` request.
  - Remove client-side OAuth token storage from `localStorage` (`frontend/src/osm_api.js`, `frontend/src/app.js`).
- **Database Tables (add to PostGIS):**
  - `users(osm_uid BIGINT PRIMARY KEY, display_name TEXT, avatar_url TEXT, created_at TIMESTAMPTZ, last_login_at TIMESTAMPTZ, leaderboard_opt_out BOOLEAN DEFAULT FALSE)`
  - `sessions(session_id TEXT PRIMARY KEY, osm_uid BIGINT REFERENCES users(osm_uid), encrypted_token TEXT, created_at TIMESTAMPTZ, expires_at TIMESTAMPTZ)`
  - `review_marks(osm_type VARCHAR(16), osm_id BIGINT, version INT, status VARCHAR(32), osm_uid BIGINT REFERENCES users(osm_uid), updated_at TIMESTAMPTZ, PRIMARY KEY (osm_type, osm_id))`
  - `review_events(id SERIAL PRIMARY KEY, osm_type VARCHAR(16), osm_id BIGINT, version INT, status VARCHAR(32), osm_uid BIGINT, created_at TIMESTAMPTZ)`
  - `edits(id SERIAL PRIMARY KEY, osm_uid BIGINT, changeset_id BIGINT, osm_type VARCHAR(16), osm_id BIGINT, old_version INT, new_version INT, tags_changed JSONB, created_at TIMESTAMPTZ)`
- **Shared `ReviewMarks` (`frontend/src/review.js`):**
  - Keep existing interface, backed by server API (`GET /api/v1/reviews`, `POST /api/v1/reviews`) when logged in, falling back to `localStorage` for guests.
  - Provide a one-time import of existing `localStorage` review marks after first login (imported marks do not count toward the edit leaderboard).
- **Server-Side Edit Proxy (`POST /api/v1/osm/changesets`):**
  - Re-fetches the live OSM object from `api.openstreetmap.org`, verifies `version` matches to prevent conflicts, and **strictly allowlists** only the tag keys `amenity`, `building`, `name:en`, and `denomination` (matching `frontend/src/editing.js`).
  - Enforces per-user rate limits (max 10 changesets/hour, max 50 elements/changeset), sets User-Agent `Manara/1.0 (+https://manara.saudiosm.org)`, uploads diff, **always closes the changeset**, and records the edit in `edits`.
  - Signed-in notes go through `POST /api/v1/osm/notes`; anonymous notes stay in the browser.
- **Backups:**
  - Nightly `pg_dump` of the user/review/history tables (`users`, `sessions`, `review_marks`, `review_events`, `edits`, `dataset_versions`, `region_stats_history`), retained for 14 days.

---

## 7. Phase 5: Community & Public Pages

- **Community / Stats Page (`/community` in Vite):**
  - **Important path note:** `/stats/*` is reserved for the Umami analytics proxy in Caddy (`deploy/Caddyfile.container`). Use `/community` (or `/dashboard`) for the public statistics page to avoid colliding with `/stats/*`.
  - Displays per-province coverage from `GET /api/v1/stats/regions`, progress over time from `GET /api/v1/stats/history`, issues breakdown, recent edits feed, and an opt-out mapper leaderboard.
- **SEO / Server-Rendered Pages:**
  - `/place/{type}/{id}` and `/region/{code}` with OpenGraph tags, `Place` JSON-LD, `hreflang`, OSM attribution, and deep links to OSM / iD / JOSM.
- **`sitemap.xml` and `robots.txt`:**
  - Regenerated on pipeline runs (`robots.txt` already disallows `/stats/`).

---

## 8. Phase 6: Operations & Monitoring

- **Health & Freshness Monitoring:**
  - Web health check: `https://manara.saudiosm.org/healthz`
  - API & DB health check: `https://manara.saudiosm.org/api/healthz`
  - Dataset freshness check: `https://manara.saudiosm.org/api/v1/meta` (`published_at` and `pbf_date`; alert if >3 days old).
- **Docker log rotation & pinned image tags.**

---

## 9. Useful Verification Commands

```bash
# 1. Run full Python test suite (42 tests: common, regions extractor, FastAPI endpoints)
python -m pytest tests/ -q

# 2. Frontend lint, build & local HTTPS preview (https://localhost:8000)
cd frontend && npm ci && npm run lint && npm run build && npm run preview

# 3. Live production health & API checks
curl -s https://manara.saudiosm.org/healthz
curl -s https://manara.saudiosm.org/api/healthz
curl -s https://manara.saudiosm.org/api/v1/meta
curl -s https://manara.saudiosm.org/api/v1/stats
curl -s https://manara.saudiosm.org/api/v1/stats/regions
curl -s "https://manara.saudiosm.org/api/v1/suggestions?bbox=46.6,24.6,46.8,24.8&limit=5"

# 4. Check VPS containers & memory usage over SSH
ssh root@159.195.192.148 "docker stats --no-stream && free -h"

# 5. Manually trigger pipeline + PostGIS load on VPS (only if needed)
ssh root@159.195.192.148 'CID=$(docker ps --filter name=e3xakpyxk2xmq19aqpyvjdjq --format "{{.Names}}" | head -n 1); docker exec $CID python run.py once --force'
```

---

## 10. Working Preferences from the User

- **Always respond in English** by default, while preserving Arabic strings in code/translations intact.
- **Ask before outward-facing actions** unless explicitly given the green light: pushing to `main` triggers automatic Coolify deployments on production.
- **Never risk an OSM block:** state explicitly how any OSM-related feature complies with OSM API & Geofabrik usage policies.
- **Never touch Rahma Health containers** on the VPS.
