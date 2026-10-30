# Manara (manara.saudiosm.org): Project Handoff

This document summarises the architecture, live infrastructure, completed phases (Phases 1–3 and Phase 6a), and upcoming roadmap (Phases 5, 4 and 6b) for **Manara** (`https://manara.saudiosm.org`), so another AI coding assistant can seamlessly continue the work.

**Where things stand:** Phases 1–3, Phase 4 (accounts & shared review), Phase 5a (`/community` page), Phase 5b (leaderboard, verified edits feed, and SEO pages), Phase 6a (operations), and Phase 6b (security review & hardening) are done. The utility-first redesign (`REDESIGN.md`) has started: **Redesign Phase 0 is done and live** (2026-10-30, see §12); Redesign Phase 1 is next. Nothing is half-finished in the code; `main` is clean.

- **Last updated:** 2026-10-30 (Phase 6b security hardening complete; next is Redesign Phase 1)
- **Repository:** `github.com/Abdullah201x/sa-places-of-worship` (branch `main` auto-deploys via Coolify)
- **Local checkout:** `C:\Users\abdul\Desktop\GCC20260707`
- **VPS SSH:** `root@159.195.192.148`

---

## 1. What the Project Is

Manara is an interactive Leaflet map of places of worship in Saudi Arabia, built from OpenStreetMap data. The UI is Arabic (RTL) by default, with an English toggle. It has three modes:
- **POI density** (clustering + heatmap);
- **Coverage gaps** (road-network grid cells lacking nearby mosques);
- **Data-improvement mode for mappers**: issue detection, a review queue, Wikidata suggestions (~54.5k missing mosques), exports (GeoJSON, CSV, KML, OSM XML, MapRoulette), and in-app tag fixes through the OSM API with OAuth2 PKCE.

A server-side Python pipeline (checks hourly, runs once per new Geofabrik update) (`pipeline/`, using `osmium`, `shapely`, `scikit-learn`, `psycopg`) turns Geofabrik's public GCC `.pbf` extract into static compressed JSON/GeoJSON datasets **and** loads them atomically into a PostGIS 17 database backing a public read-only FastAPI service (`backend/`).

| Dataset File | Records | Contents |
|---|---|---|
| `summary.json` | — | Counts, `updated_at` (also the frontend's cache-busting `?v=` token), `pbf_date` |
| `places_of_worship_sa.geojson` | ~14,021 | OSM places of worship (`node`, `way`, `relation` centroids + tags, `version`, `edited_at`) |
| `worship_gaps_sa.json` | ~59,695 | Road-network gap grid cells (`[grid_x, grid_y, road_length_m, gap_score, urgency_score]`) |
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
| **Pipeline Worker** | `e3xakpyxk2xmq19aqpyvjdjq` (`manara-pipeline`) | `pipeline/Dockerfile` | None | `1.5 GiB` (`1.5 CPU`) | ~17 MiB idle (~970 MiB peak) | Runs `python run.py schedule` (hourly check of Geofabrik's `state.txt`; a full run only when a new update exists, see §4); mounts volume `manara-state:/state` and host `/data/manara/published:/published` |
| **FastAPI Backend** | `mp6ebt0ybcqvpmk4bke8d56w` (`manara-api`) | `backend/Dockerfile` | `:8010` | `256 MiB` | ~45 MiB | Consistent container name enabled; Docker network alias `manara-api` on `coolify` network; proxied by Caddy `handle /api/*` |
| **PostGIS Database** | `9uzoip4gqaxybg3e5oymh8sg` (`manara-db`) | `postgis/postgis:17-3.5-alpine` | `:5432` | `512 MiB` | ~241 MiB | Database `manara`, user `manara`, extensions `postgis` and `pg_trgm` enabled |

- **Internal `MANARA_DATABASE_URL`** (configured on both `manara-pipeline` and `manara-api`). **Secrets live only in Coolify environment variables, never in docs or git.** The password that used to be written here (commit `1450983`) must be rotated:
  ```text
  postgresql://manara:<see Coolify env var MANARA_DATABASE_URL>@9uzoip4gqaxybg3e5oymh8sg:5432/manara
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
- **Approved 2026-10-30 for the redesign, not built yet** (`REDESIGN.md` §3.3, decisions D3/D4):
  - OSM's own minutely replication diffs (`planet.openstreetmap.org/replication/minute`, which redirects to OSMF's S3 mirror) may be read by one dedicated container (`manara-live`), for the change feed only: sequential, one `state.txt` check per minute at most, identifying User-Agent, backoff on 429/503. The diffs carry `user`/`uid`/`changeset`; keep only `changeset`, never store or log names or uids.
  - Osmose (`osmose.openstreetmap.fr/api/0.3`) and Overpass (`overpass-api.de`) may be called from the browser **on click only**, one request at a time, bbox-limited; both send `Access-Control-Allow-Origin: *` and need a CSP `connect-src` addition.
- **Never hand-patch published datasets or the committed copies.** On 2026-10-28 a mosque added from Manara was patched into `/data/manara/published/current/places_of_worship_sa.geojson` and into the repo, together with its editor's name, uid and changeset. Let the next pipeline run pick new objects up from the extract.

---

## 3. Phase 1: DONE & Live (Vite Frontend + Caddy Container)

### Frontend (`frontend/`)
- **Vite MPA**:
  - `index.html` (map), `about.html`, `privacy.html` (bilingual `[data-lang]` blocks with shared i18n module).
  - ES modules in `frontend/src/`: `main.js`, `app.js`, `i18n.js`, `translations*.js`, `arabic.js`, `review.js`, `exporters.js`, `osm_api.js`, `editing.js`, `analytics.js`, `page.js`, `leaflet-setup.js`, plus (redesign Phase 0) `keys.js` (layout-independent shortcuts), `validator.js` (the 13 issue rules) and `timeago.js` (the data-age label).
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
3. **Automated runner (`pipeline/run.py` & `pipeline/Dockerfile`):**
   - Runs `python run.py schedule`. Since 2026-10-30 it **checks hourly** (`MANARA_CHECK_EVERY_MIN`, default 60): one small GET of the extract's replication `state.txt`, and a full run only when Geofabrik's sequence is ahead of the local extract's. The old fixed 23:30 UTC run missed about half of Geofabrik's updates, whose publish time varies from about 20:45 UTC to 12:56 UTC the next day; on 2026-10-28 it checked 92 s too early and the site stayed a day staler.
   - A run that **failed** after the diffs were applied is retried with `--force` at most every 6 hours (otherwise the already-updated extract would hide that update until the next one).
   - `/state/status.json` records `last_attempt`, `last_result` (`published` / `no new data` / `failed`) and `last_error`. `duration_s` is only written on success.
   - `summary.json` now also has `pbf_timestamp` (full replication time of the extract) next to `pbf_date`; the frontend's data-age label reads it.
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
   - Rate-limited with `slowapi` (`120/minute`), connection-pooled with `psycopg_pool`, and tested in CI (`.github/workflows/ci.yml` runs all 46 pytest unit tests + frontend lint & build).
   - **Live Endpoints:**
     - `GET /api/healthz` -> `{"status":"ok"}`
     - `GET /api/healthz/freshness` -> 200 with `{status, version, published_at, age_hours}`; **503** when the newest `dataset_versions.published_at` is older than `MANARA_MAX_DATASET_AGE_HOURS` (default 72) or missing. For the external monitor.
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

## 6. Recommended Order for the Remaining Work

1. ✅ **Phase 6a** (done 2026-10-28, see §9): DB password rotated, nightly backups, uptime monitors, freshness check, pinned tags, Dependabot. Only the Telegram alerts remain, and the user will do those.
2. ✅ **Phase 5a** (done 2026-10-28, see §8): the public `/community` stats page (`frontend/community.html`, `frontend/src/community.js`).
3. ✅ **Phase 4** (done 2026-10-28, see §7): accounts and guarded shared review (hybrid model B).
4. ✅ **Phase 5b** (done 2026-10-28, see §8): opt-in leaderboard, recent verified edits feed, and SEO pages (/region, /place, /sitemap.xml).
5. ✅ **Phase 6b** (done 2026-10-30, see §14): final security review and verification, transaction atomicity, batch changeset updates, proxy multi-hop headers, CSRF referer fallback, and test suite expansion.
6. ✅ **Redesign Phase 0** (done 2026-10-30, see §12).
7. **Redesign Phase 1 (NEXT):** Astro + Svelte shell, routing, command palette and the list-first `/qa` workspace (`REDESIGN.md` §5). Write a step-by-step plan for the user first.

---

## 7. Phase 4: Accounts & Shared Review (DECIDED: hybrid login model)

### Login model "B. Hybrid" (chosen by the user)
- **OSM edits stay in the browser**, exactly as today: PKCE OAuth in `frontend/src/osm_api.js`, uploads from `editing.js`. Nothing about OSM writes moves to the server.
- **Manara session (`POST /auth/session`):**
  - After a successful browser OSM login, the frontend sends the access token **once** to `POST /auth/session`.
  - The server calls `GET https://api.openstreetmap.org/api/0.6/user/details.json` with it **once**, reads `id`, `display_name`, `img.href`, `account_created` and `changesets.count`, upserts `users`, then **discards the token**. It is never stored or logged.
  - It returns cookie `__Host-manara_session` (random 256-bit ID, stored **hashed** in `sessions`; `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`; 30-day rolling expiry).
- **Other endpoints:** `POST /auth/logout` (deletes the session row) and `GET /api/v1/me`.
- **Caddy:** add `handle /auth/*` to `deploy/Caddyfile.container`, proxied to `{$MANARA_API_URL:http://manara-api:8010}`.
- **CSRF:** every state-changing request (`POST`/`PUT`/`DELETE`) needs `Origin: https://manara.saudiosm.org` plus the header `X-Manara-CSRF: 1`. Reject anything else with 403.
- **Rate limits:** `/auth/session` 10/min per IP; writes 60/min per user.
- **OSM compliance:**
  - one `user/details` read per login, triggered by the user;
  - one `GET /api/0.6/changeset/{id}` read per reported changeset (below);
  - both with User-Agent `Manara/1.0 (+https://manara.saudiosm.org)`, honouring 429 `Retry-After`;
  - no polling, and no bulk reads.

### Tables (PostGIS DB, created by an Alembic migration in `backend/`)
- `users(osm_uid BIGINT PK, display_name TEXT, avatar_url TEXT, osm_changesets INT, osm_account_created TIMESTAMPTZ, created_at, last_login_at, leaderboard_opt_in BOOLEAN DEFAULT FALSE, is_admin BOOLEAN DEFAULT FALSE)`
  - `is_admin` comes from the env allowlist `MANARA_ADMIN_UIDS`.
- `sessions(token_hash TEXT PK, osm_uid BIGINT REFERENCES users, created_at, expires_at, last_seen_at)`
- `review_marks(osm_type, osm_id, osm_uid, status, version, verified_changeset BIGINT NULL, created_at, PRIMARY KEY (osm_type, osm_id, osm_uid))`
  - One row **per user**; shared visibility is decided at query time (below).
- `review_events(id, osm_type, osm_id, osm_uid, status, version, created_at)`: append-only audit log.
- `edits(changeset_id BIGINT PK, osm_uid, objects JSONB, comment TEXT, verified_at TIMESTAMPTZ, created_at)`

### Shared review marks: "guarded sharing" (chosen)
- **`skipped` is personal:** it is only ever applied to the user who set it.
- **`fixed` hides an issue from everyone only if:**
  - the user has at least `MANARA_MIN_CHANGESETS` (default 10) OSM changesets, **and**
  - either the mark has a `verified_changeset` that touched that object, **or** no newer dataset has arrived yet.
  - A `fixed` mark without a verified edit expires automatically when the next pipeline run still shows the issue at the same `version`.
- **Version rule (as today):** any mark expires when the object's `version` increases.
- **Admins** can revoke all marks by a user (`DELETE /api/v1/admin/users/{uid}/marks`).
- **API:**
  - `GET /api/v1/reviews`: the shared marks plus the caller's own marks;
  - `PUT /api/v1/reviews/{type}/{id}` with `{status, version}`;
  - `DELETE /api/v1/reviews/{type}/{id}`.
- **`ReviewMarks` in `frontend/src/review.js`** keeps its interface. It is server-backed when logged in and uses `localStorage` for guests. After the first login it offers a one-time import of the `localStorage` marks; imported marks are personal and unverified.

### Edit recording and verification
- After a successful upload, the browser calls `POST /api/v1/edits {changeset_id}`.
- The server fetches `GET /api/0.6/changeset/{id}` **once** and accepts it only if:
  - `uid` equals the session user;
  - the `hashtags` or `comment` tag contains `#sa-worship-map`;
  - the changeset is closed.
- It then stores the edited objects (`/api/0.6/changeset/{id}/download`, also one read) and sets `verified_changeset` on that user's matching `fixed` marks.
- Only verified edits count for the leaderboard and the feed. Edit history imported from `localStorage` is shown to its owner only.

### Privacy page
- Update `frontend/privacy.html`. It must cover:
  - the Manara session cookie (strictly necessary, so no banner is needed);
  - what is stored per user: OSM uid, display name, avatar URL, changeset count, marks, verified edits;
  - that the leaderboard is **opt-in**;
  - how to delete an account. Add `DELETE /api/v1/me`, which removes the user's rows and their marks.

---

## 8. Phase 5: Community & Public Pages

- ✅ **5a. `/community` (Vite page, needs no accounts) — DONE (2026-10-28):**
  - per-province coverage (`/api/v1/stats/regions`), progress over time (`/api/v1/stats/history`), and an issue breakdown (`/api/v1/stats`);
  - bilingual and RTL.
  - Do **not** use `/stats/*`: that path is reserved for the Umami proxy.
  - **No backend changes are needed:** all three endpoints are live (§5). Follow the pattern of `frontend/about.html` / `privacy.html` (shared `i18n.js`, `page.js`, `styles/page.css`; `about.html` is the template: `<body data-title-key=...>`, `[data-lang]` blocks, language toggle button `#btn-toggle-lang`). Register the page in **both** places in `frontend/vite.config.js`: the `PAGES` set (line ~51, the dev/preview rewrite of `/about` and `/privacy`) and `build.rollupOptions.input` (line ~86). In production Caddy already serves `/community` through its `try_files {path} {path}.html` rule once `community.html` is built. Also link to it from `index.html`/`about.html` if the user wants it discoverable, and add `canonical`/description meta like `about.html`.
  - `region_stats_history` only started filling on 2026-10-28 (one snapshot per pipeline run, two so far), so the time-series chart starts nearly empty. The page must handle 0–2 points gracefully.
  - Charts: the user has not chosen a library. The recommended approach is plain CSS bars and inline SVG, with no new dependency (the site is fully self-hosted, no CDN). Ask the user before adding a chart library.
  - The CSP in `deploy/Caddyfile.container` is `default-src 'self'` with `connect-src 'self' ...`, so same-origin `/api/*` calls work with no CSP change. Any new external host would need one.
  - No OSM API calls, nothing stored, so there is no OSM compliance risk. State this in the plan.
- **5b. After Phase 4:**
  - **opt-in** leaderboard (verified edits only; `users.leaderboard_opt_in`);
  - recent verified edits feed, read from the `edits` table. No OSM polling.
- **SEO pages** (FastAPI with Jinja, `Cache-Control: public, max-age=3600`):
  - `/region/{code}`: 13 rich pages.
  - `/place/{type}/{id}`: **only named places are indexable**; generic or unnamed places get `noindex`.
  - All of them: OG tags, `Place` JSON-LD, `hreflang` ar/en, OSM attribution, and links to OSM/iD/JOSM.
  - `sitemap.xml` regenerated after each pipeline load.
- **Wikidata suggestions:** keep the static pre-compressed bundle in the frontend (1.1 MB brotli, cached, filtered instantly). `/api/v1/suggestions` stays for other uses.

---

## 9. Phase 6: Operations & Monitoring

**Phase 6a is DONE (2026-10-28), except the Telegram alerts.** Everything below is live and was checked.

### Done and verified
- **DB password rotated** by the user in Coolify (`MANARA_DATABASE_URL` on both `manara-api` and `manara-pipeline`). A forced `run.py once --force` afterwards loaded all tables and swapped them atomically (24 s), so reads and writes both work. The old password is still in git history (commit `1450983`); that is why it was rotated.
- **Freshness check:** `GET /api/healthz/freshness` returns 200 with `{status, version, published_at, age_hours}`, or **503** when the newest `dataset_versions.published_at` is older than `MANARA_MAX_DATASET_AGE_HOURS` (default 72) or missing. Code in `backend/app/routers/healthz.py`, tests in `tests/test_backend_api.py`.
- **Health routes answer GET and HEAD.** UptimeRobot checks with `HEAD`; the routes were `GET`-only at first and returned 405, which made two monitors go red (fixed in `0e4f733`). Keep `methods=["GET", "HEAD"]` on any new health route.
- **UptimeRobot** (the user's free account, 5-minute checks, email alerts) has three monitors: `https://manara.saudiosm.org` (home page), `/api/healthz`, `/api/healthz/freshness`. The Caddy-only `/healthz` is not monitored (the home page covers the web container).
- **Backups (DECIDED: on the VPS only):**
  - Coolify scheduled backup on `manara-db`: database `manara`, frequency `daily` (00:00 UTC, 03:00 Riyadh; the pipeline no longer runs at a fixed time, which is fine: `pg_dump` takes a consistent snapshot and the loader's table swap waits for it), **14 days** local retention, no S3.
  - Files: `/data/coolify/backups/databases/root-team-0/manara-db-9uzoip4gqaxybg3e5oymh8sg/pg-dump-manara-*.dmp` (custom format, about 6.7 MB).
  - The scope is the **whole `manara` database**, not only the user tables (this replaced the earlier plan, because the user tables do not exist yet and the dump is small). Nothing needs changing when Phase 4 adds tables.
  - Verified: a manual `pg_dump -Fc` restored into a throwaway database with identical row counts (14,021 places, 59,695 gaps, 54,504 suggestions, 13 regions, 2 dataset versions), and Coolify's own dump lists all the data tables in `pg_restore -l`.
  - ⚠️ Risk the user accepted: losing the VPS disk loses the backups too. **Optional safety net:** a weekly manual `scp` of the newest dump to the desktop. Not set up.
- **Hygiene:**
  - Image tags pinned: `caddy:2.11-alpine`, `node:26-alpine`, `alpine:3.24` and `python:3.12-slim` (as of 2026-10-30), `postgis/postgis:17-3.5-alpine` (set in Coolify).
  - `.github/dependabot.yml`: weekly updates for npm (`/frontend`), pip (`/backend`, `/pipeline`), docker (`/`, `/backend`, `/pipeline`) and github-actions. Expect its first PRs on GitHub; review them rather than auto-merging, because a merge to `main` deploys to production.

### Still to do
- **Coolify Telegram notifications** (user will do this later; it replaces the earlier email plan): a bot token from `@BotFather` and a chat ID, entered only in the Coolify UI under Notifications → Telegram. Enable failed deployments and container stopped. When done, also set "Missing backup alert after" on the backup schedule to about 36 hours (it is `0`, which means off).
- **Phase 6b:** a security review of the Phase 4 auth code before it goes live; rotate any secret that ever lands in a doc or commit.

### Restore runbook
Never restore over the live `manara` database without the user's explicit OK. To test a backup:
```bash
ssh root@159.195.192.148
C=$(docker ps --filter name=9uzoip4gqaxybg3e5oymh8sg --format "{{.Names}}" | head -n1)
# copy the newest Coolify dump into the DB container
F=$(ls -t /data/coolify/backups/databases/root-team-0/manara-db-*/pg-dump-manara-*.dmp | head -1)
docker cp "$F" $C:/tmp/restore.dmp
docker exec $C psql -U manara -d postgres -c "CREATE DATABASE manara_restore_test;"
docker exec $C pg_restore -U manara -d manara_restore_test --no-owner /tmp/restore.dmp
docker exec $C psql -U manara -d manara_restore_test -Atc "select count(*) from places"   # compare with the live DB
docker exec $C psql -U manara -d postgres -c "DROP DATABASE manara_restore_test;"
docker exec $C rm -f /tmp/restore.dmp
```

### Coolify 4.5 UI quirks (learned the hard way)
- The backup schedule page has **no Save button**. Fields save on blur: press Enter to make a chip, then Tab or click outside, and wait for the toast. **"Back Up Now" does not save the form** and runs with whatever is stored.
- Always confirm a setting really stuck by reading Coolify's own DB (read-only):
  `ssh root@159.195.192.148 'docker exec coolify-db psql -U coolify -d coolify -Atc "select frequency, databases_to_backup, database_backup_retention_days_locally, enabled from scheduled_database_backups;"'`
  and recent runs with `select status, size, filename from scheduled_database_backup_executions order by id desc limit 3;`.
- The default `databases_to_backup` is `postgres` (an empty 5.7 KB dump). A good dump is named `pg-dump-manara-*` and is several MB.

---

## 10. Useful Verification Commands

```bash
# 1. Run full Python test suite (82 tests: common, regions extractor, Phase 4/5b, transliteration NLP, FastAPI endpoints, pipeline scheduler)
#    and the frontend Vitest suite (45 tests: presets, validator rules, shortcut keys, data-age label): cd frontend && npm run test
python -m pytest tests/ -q

# 2. Frontend lint, build & local HTTPS preview (https://localhost:8000)
cd frontend && npm ci && npm run lint && npm run build && npm run preview

# 3. Live production health & API checks
curl -s https://manara.saudiosm.org/healthz
curl -s https://manara.saudiosm.org/api/healthz
curl -s https://manara.saudiosm.org/api/healthz/freshness   # 200 normally, 503 when the dataset is stale
curl -s https://manara.saudiosm.org/api/v1/meta
curl -s https://manara.saudiosm.org/api/v1/stats
curl -s https://manara.saudiosm.org/api/v1/stats/regions
curl -s "https://manara.saudiosm.org/api/v1/suggestions?bbox=46.6,24.6,46.8,24.8&limit=5"
curl -s "https://manara.saudiosm.org/api/v1/transliterate?name=%D8%AC%D8%A7%D9%85%D8%B9%20%D8%A7%D9%84%D9%85%D9%84%D9%83%20%D9%81%D9%87%D8%AF"

# 4. Check VPS containers & memory usage over SSH
ssh root@159.195.192.148 "docker stats --no-stream && free -h"

# 5. Manually trigger pipeline + PostGIS load on VPS (only if needed)
ssh root@159.195.192.148 'CID=$(docker ps --filter name=e3xakpyxk2xmq19aqpyvjdjq --format "{{.Names}}" | head -n 1); docker exec $CID python run.py once --force'
```

---

## 11. Working Preferences from the User

- **Always respond in English** by default, while preserving Arabic strings in code/translations intact.
- **Ask before outward-facing actions** unless explicitly given the green light: pushing to `main` triggers automatic Coolify deployments on production.
- **Never risk an OSM block:** state explicitly how any OSM-related feature complies with OSM API & Geofabrik usage policies.
- **Never touch Rahma Health containers** on the VPS.
- **Secrets live only in Coolify environment variables:** database URLs and passwords, API keys, OAuth client secrets, encryption keys.
  - Never write them into docs, code, commit messages, logs or chat.
  - In docs, refer to the variable name (for example `MANARA_DATABASE_URL`).
  - If a secret ever lands in git, **rotate it**; deleting the line doesn't remove it from history.
- **Plan first, then build; commit locally, but ask before every `git push`** (a push to `main` redeploys production). Earlier approval of one push does not cover the next. After a push, check the live endpoints with `curl` (Coolify takes about 1–2 minutes to rebuild).
- **The user is not a sysadmin.** Explain terms plainly (for example SMTP, cron) and give exact click-by-click steps for Coolify and third-party UIs. Never ask the user to paste a secret into chat.

### Environment gotchas (Windows dev machine)
- The shell is Git Bash/PowerShell on Windows. Python's default encoding there is cp1252, so a script that reads a repo file containing Arabic must pass `encoding="utf-8"`; otherwise it crashes (this happened with `tests/test_backend_api.py`).
- Git prints "LF will be replaced by CRLF" warnings on commit. They are harmless.
- `ssh root@159.195.192.148 ... docker exec ... run.py once --force` takes about 2 minutes. The SSH connection may reset right after the final `Published v...` line; that is harmless. Confirm with `curl -s https://manara.saudiosm.org/api/healthz/freshness`.
- Do not run `once --force` casually: peak memory is about 970 MiB on a VPS with about 2.3 GiB available and a neighbour (Rahma) on it.

---

## 12. Utility-First Redesign (`REDESIGN.md`)

`REDESIGN.md` is the plan for turning Manara into a utility-first, keyboard-driven, bilingual workspace: functional audit, sitemap, the Task Tracker / Tagging Directory / Live Change Monitor specs, data models and the phased roadmap. `OSM_IDEAS.md` holds the earlier ideas it builds on.

### Decisions (user, 2026-10-30)
| # | Decision |
|---|---|
| D1 | Scope: **places of worship only** |
| D2 | Frontend: **Astro (static output) + Svelte islands**; no SSR server, no Tailwind; MapLibre in redesign Phase 5 |
| D3 | Change feed: **add OSM minutely replication diffs** (new `manara-live` container) with an Osmose-style age label |
| D4 | Osmose and Overpass: **on-click browser calls** |
| D5 | English: **`/en/` prefix for content pages**, `lang` setting for the workspaces |
| D6 | Sprints (task tracker): **admins only** (`MANARA_ADMIN_UIDS`), no coordinator role |

### Redesign Phase 0: DONE & live (2026-10-30)
- `a137a34` Shortcuts work with any keyboard layout (`frontend/src/keys.js`). They used `e.key`, so the Arabic layout broke every shortcut.
- `a8d259f` Issue rules moved to `frontend/src/validator.js` (`RULES`, `RULE_IDS`, `evaluateRules`). **Rule ids are snake_case and must never be renamed** (filters, permalinks, exports). Output was verified identical to the old code on all places.
- `e33425d` Data-age label in the sidebar (`OSM data · 20h`, ●/▲/✕ at 36 h / 72 h, Riyadh + UTC on hover), from `summary.json` `pbf_timestamp`, with clock skew corrected from the `Date` header.
- `0343368` `index.css` uses logical properties; the `[dir="ltr"]` override block is gone (two intended exceptions are commented). 53 styling inline styles moved to the stylesheet; only the 15 JS-toggled `display:none` states stay inline until Phase 1.
- Dropped: loading Wikidata suggestions by bbox. The bundle is already lazy (938 KB brotli), and the bbox API would lose the country-wide clusters, the counts and search (keeps the §8 decision).
- Verification approach that worked: headless Chrome via `puppeteer-core` (driving the installed Chrome, tool kept outside the repo) taking before/after screenshots in ar/en, desktop/mobile, with remote tiles blocked and animations disabled, plus per-element position/size comparisons.

### Follow-ups done the same day
- `9b9e440` The pipeline checks hourly instead of once at 23:30 UTC (see §4).
- `c14e2e3`, `e29b638` The committed datasets were replaced with the public-extract versions. The old committed places file came from the login-only extract and named 484 contributors (the old values remain in the private repo's history). The committed gaps grid was kept, because the published one predated `urgency_score`.

---

## 13. Session Record, 2026-10-30 (for the next agent)

This section summarises the whole chat of 2026-10-30, so a new agent can continue without it. Facts below were checked during the session; re-check anything time-sensitive.

### 13.1 What the user asked, in order
1. **Redesign proposal.** The user attached `design prompt.md`: a generic brief to re-architect Manara as a utility-first, dense, keyboard-driven, bilingual (Arabic-primary) platform with five deliverables (audit, sitemap/wireframes, three module specs, TypeScript data models, phased plan). The answer was grounded in the real codebase instead of the generic brief and written to `REDESIGN.md`.
2. **Decisions.** The user answered the six open questions (§12 table). For D3 they asked for an Osmose-style age indicator, like `<span class="v-time-ago__text">20h</span>` on osmose.openstreetmap.fr. D6 needed a plain-language explanation; they chose admins only.
3. **"Let us start with Phase 0"**: done (§12). Item 4 (bbox suggestions) was dropped after the user chose "Skip it" when shown the measurements.
4. **"yes"** to pushing Phase 0. Pushed `a7cac6d..0343368`; Coolify deployed in about 90 s; live checks passed.
5. **"what is next?"**: proposed 1) find why the pipeline didn't publish, 2) remove contributor names from committed data, 3) commit docs and update this file, 4) Redesign Phase 1.
6. **"do the first three before phase 1"**: done (§12 "Follow-ups").
7. **"export this chat in the handoff"**: this section.

### 13.2 Current state (end of session)
- **Live on production:** everything up to `0343368` (Redesign Phase 0).
- **Committed locally, NOT pushed** (the user had not answered the push question when the session ended):
  - `9b9e440` hourly pipeline check
  - `c14e2e3`, `e29b638` cleaned committed datasets
  - `722291b` docs
  - the commit that adds this section

  **Ask the user before pushing** (a push to `main` redeploys production). Once pushed, the pipeline container restarts and its first hourly check should immediately publish Geofabrik update 3869 (the local extract on the VPS was at 3868). If it is not pushed, the old scheduler that is live now runs at 23:30 UTC and should also pick up 3869.
- **Live data was about 39 h old** at the end of the session (published `v20261028T071645Z`). The live `summary.json` has no `pbf_timestamp` yet, so the new data-age label still shows the plain date (`بيانات OSM بتاريخ 2026-10-27`) until the next publish.
- **Production gaps file lacks `urgency_score`** (it predates that code). The frontend falls back to `gap_score`, so the "high urgency" filter is approximate until the next publish.
- **The live published places file has one hand-patched feature** (node 14325238501, "Al-Nawawi Mosque", added from Manara on 2026-10-28) carrying `last_edited_by`, `user_id`, `changeset_id`. The next pipeline run overwrites it. Do not hand-patch published data again (§2).
- Untracked on purpose: `design prompt.md` (the user's original brief).
- Tests: `python -m pytest tests -q` gives 82 passed; `cd frontend && npm run test` gives 45 passed; lint and build are clean.

### 13.3 Still open, in the recommended order
1. **Push decision** for the four local commits plus this one (above).
2. **Check the first run after the push or at 23:30 UTC:**
   - `ssh root@159.195.192.148`, then `docker logs` on the `e3xakpyxk2xmq19aqpyvjdjq` container, and `cat /state/status.json` inside it;
   - `curl -s https://manara.saudiosm.org/data/summary.json` should now include `pbf_timestamp`;
   - the gaps file should have `urgency_score` in `fields`.
3. **Phase 6b security review** of the Phase 4 auth code (`backend/app/auth.py`, `routers/auth.py`, `reviews.py`, `edits.py`). It was never done, and should come before Redesign Phase 1 adds more account-backed pages.
4. **Redesign Phase 1** (`REDESIGN.md` §5): write a step-by-step plan and get the user's approval before building (the user's standing preference: plan first, then build).
5. Minor / optional:
   - the Coolify Telegram alerts (the user will do these);
   - two `min-height` inline styles in `frontend/community.html`;
   - `transliteration.py` is duplicated between `backend/app/` and `pipeline/`;
   - `cert.pem` / `key.pem` sit in the repo root (gitignored).

### 13.4 Facts verified during the session (useful later)
- **Planet replication:**
  - `https://planet.openstreetmap.org/replication/minute/state.txt` redirects (302) to `osm-planet-eu-central-1.s3.dualstack.eu-central-1.amazonaws.com`; clients must follow redirects.
  - One minute diff was about 45 KB gzipped; one hour diff about 4.4 MB.
  - Diffs include `user`, `uid`, `changeset`. Deleted elements carry no tags (nodes keep lat/lon), and ways have no coordinates.
- **Browser calls:** `osmose.openstreetmap.fr/api/0.3/issues?bbox=…` and `overpass-api.de` both answer with `Access-Control-Allow-Origin: *`.
- **Geofabrik GCC updates:** `https://download.geofabrik.de/asia/gcc-states-updates/state.txt`. Publish times of sequences 3850–3869 ranged from 20:45 UTC to 12:56 UTC the next day.
- **Live compressed sizes (brotli):** places 257 KB, gaps 425 KB, suggestions 938 KB. Suggestions load only when toggled on.
- **The GitHub repo is private:** the anonymous API returns 404. The `gh` CLI is not installed on this machine.
- **Windows shell gotchas found this session:**
  - Bash heredocs containing apostrophes sometimes fail to parse in the agent's Bash tool. Write Python helper scripts to a temp file instead.
  - `python -I` ignores `PYTHONIOENCODING`, and the console is cp1252, so print only ASCII, or `ascii()` Arabic.
  - `cmd | tail` hides the exit code. Check pytest's own exit status before committing.
- **CSS:** `ar-SA` dates default to the Hijri calendar; use `ar-SA-u-ca-gregory` where a Gregorian date is meant. `fmtNum` (`ar-SA`) gives Arabic-Indic digits; the redesign plans Western digits in Phase 1 (`REDESIGN.md` §3.5).
- **UI regression checking that worked:** `puppeteer-core` driving the installed Chrome (`C:/Program Files/Google/Chrome/Application/chrome.exe`) against `npm run dev` with `MANARA_DATA_DIR` pointing to a temp copy of the data:
  - block `arcgisonline|cartocdn|openstreetmap.org|/stats/` requests, and disable animations and transitions;
  - wait for `#loading-overlay.hidden`, set `localStorage.sidebar_collapsed=false`;
  - shoot ar/en at 1440×2000 and 390×844; compare with `pixelmatch`, then compare element positions and sizes to tell layout changes from scroll or timing.
  - Keep the tool outside the repo; it is not a project dependency.

---

## 14. Phase 6b Security Review & Hardening Record (2026-10-30)

Completed Phase 6b security review of the Phase 4 auth, review marks, and edit reporting layer (`backend/app/auth.py`, `routers/auth.py`, `reviews.py`, `edits.py`):

### 14.1 Hardening Patches Applied
1. **Transaction Atomicity:**
   - `backend/app/routers/reviews.py`: wrapped `set_review_mark` (marks upsert + events log) and `delete_review_mark` (delete + events log) in `with conn.transaction():`.
   - `backend/app/routers/auth.py`: wrapped user upsert and session token creation in `with conn.transaction():`.
   - `backend/app/routers/edits.py`: wrapped edit insertion and mark binding in `with conn.transaction():`.
2. **Batching and DoS Mitigation in `edits.py`:**
   - Replaced iterative single-row `UPDATE review_marks` loop with a single atomic batch query: `UPDATE review_marks SET verified_changeset = %s WHERE osm_uid = %s AND status = 'fixed' AND (osm_type, osm_id) IN (SELECT * FROM unnest(%s::text[], %s::bigint[]));`.
   - Capped XML download text parsing (`MAX_CHANGESET_XML_BYTES = 5 MB`) to prevent memory exhaustion.
3. **Multi-Hop Reverse Proxy Header Parsing:**
   - Standardized `is_request_https(request)` to check `request.url.scheme == "https"` and parse comma-separated `X-Forwarded-Proto` (`proto.split(",")[0].strip().lower() == "https"`), ensuring reliable `__Host-` cookie setting behind Traefik + Caddy.
4. **CSRF Referer Fallback:**
   - In `verify_csrf`, when `Origin` header is omitted by privacy-preserving browser configurations, falls back to parsing `Referer` and matching against `ALLOWED_ORIGINS`.
5. **Robust OSM User Dict Parsing:**
   - Fixed potential `AttributeError` when OSM API returns `"img": null` or `"changesets": null` by safely checking dict types before extracting avatar URLs and counts.
6. **Codebase Cleanups:**
   - Removed unused duplicate `pipeline/transliteration.py` (canonical module is `backend/app/transliteration.py`).
   - Removed obsolete root `cert.pem` and `key.pem` files.
   - Replaced inline `min-height: 160px;` styles in `frontend/community.html` with `.skeleton-block.skeleton-feed` in `frontend/src/styles/page.css`.
7. **Test Suite Expansion:**
   - Added tests in `tests/test_phase4_phase5b.py` for CSRF referer fallback, multi-hop proxy HTTPS cookie detection, successful edit verification with changeset XML object parsing and mark binding, and edit author mismatch rejection.
   - Full test suite: 86 passed Python tests (`pytest`), 45 passed Vitest tests, clean ESLint and Vite build.

---

## 15. Redesign Phase 1: Shell, Navigation & Issues Service Record (2026-10-30)

Started Phase 1 implementation from `REDESIGN.md` §5:

### 15.1 Completed Items
1. **Typography & Font Optimization (§2.4):**
   - Removed `@fontsource-variable/outfit` and `@fontsource-variable/plus-jakarta-sans`.
   - Standardized on self-hosted Cairo Variable and system monospace stack (`ui-monospace, ...`).
   - Saved 7 font bundles (~100 KB payload reduction).
2. **Backend QA Issues Service (`GET /api/v1/issues`):**
   - Created `backend/app/routers/issues.py` supporting rule, region, severity, and review status filtering.
   - Added `issues` table to `backend/app/schema.py`.
   - Added test in `tests/test_backend_api.py`.
3. **AppShell Layout & Status Bar (§2.2):**
   - Added 40px TopBar (`#app-topbar`) with branding, workspace tabs (`Map`, `QA`, `Community`), search trigger, live freshness indicator, language toggle, and auth button.
   - Added 24px StatusBar (`#app-statusbar`) with active version, visible items count, selected place indicator, and keyboard shortcuts helper.
4. **Command Palette (`Ctrl+K` or `/`):**
   - Built accessible modal combobox in `frontend/src/palette.js` matching Saudi regions, QA rules, and quick actions.
   - Added unit test suite in `frontend/tests/palette.test.js`.
5. **Testing & Build:**
   - Vitest: 50 passed (5 test files).
   - Pytest: 87 passed.
   - ESLint: 0 errors, 0 warnings.
   - Vite: clean production build.

### 15.2 QA Workspace & State Decoupling (2026-10-30)
1. **List-First QA Workspace (`qa_view.js` & `index.html`):**
   - Implemented `/qa` list-first triage workspace toggleable via `L` key or topbar `QA` tab.
   - Keyboard navigation: `J`/`K` navigation, `Enter` to inspect place on map, `F` to mark fixed, `S` to mark skipped, `L`/`Esc` to return to map.
   - Multi-criteria filter toolbar: rule ID, administrative region (SA-01..SA-13), review status, and dynamic sorting (severity, distance to map center, name).
   - Resilient issue resolution: queries `GET /api/v1/issues?limit=200` with graceful client-side fallback to evaluating local `allPlaces` using `evaluateRules(props)`.
   - Severity and status badges with Arabic/English localization and Haversine distance formatting.
2. **Central State Store & Mode System (`store.js` & `modes.js`):**
   - Created reactive store holding workspace mode, filters, selection, and dataset stats with observable subscription hooks.
   - Created iD-style mode state machine with explicit `enter()` and `exit()` lifecycle hooks.
   - Wired into `app.js` for seamless mode switching and map selection synchronization.
3. **Verification & Tests:**
   - Added `frontend/tests/qa_view.test.js` (7 unit tests).
   - Added `frontend/tests/store.test.js` (5 unit tests).
   - Vitest: 62 passed across 7 test suites.
   - Pytest: 87 passed.
   - ESLint: 0 errors, 0 warnings.
   - Vite: production build succeeds in <400 ms.

---

## 16. Redesign Phase 2a: Change Feed, Rules & Ingestion Hardening (2026-10-30)

Started Phase 2a from `REDESIGN.md` §3.3 & §5:

### 16.1 Completed Items
1. **Shared Worship Tag Predicate (`pipeline/worship_tags.py`):**
   - Single canonical predicate `is_worship_tagged(tags)` checking projects' places of worship (`amenity in ('place_of_worship', 'mosque') or building == 'mosque'`).
   - Integrated with `pipeline/common.py` for backward compatibility.
2. **Change Flags & Tag Diff Evaluator (`pipeline/change_rules.py`):**
   - Implemented rules from §3.3.6: `deleted-named-mosque`, `name-removed`, `religion-changed`, `amenity-removed`, `new-duplicate`, `name-ar-mismatch`, `left-boundary`, `building-downgraded`, `issue-fixed`.
   - Built `compute_tag_diff(old_tags, new_tags)` for granular tag diffs.
3. **Daily Differential Analysis Engine (`pipeline/detect_changes.py`):**
   - Differential analyzer detecting `created`, `modified`, `deleted`, and `upgraded` places (subsumed POI node to building outline transition).
   - Distance calculation and live replication event reconciliation.
4. **Automated Pipeline DB Ingestion (`pipeline/load_db.py`):**
   - Schema now initializes and atomically swaps `issues` alongside `places`, `gaps`, and `suggestions`.
   - Pipeline automatically populates QA issues during daily ingestion.
5. **Backend Changes & Freshness API (`backend/app/routers/changes.py`):**
   - `GET /api/v1/changes`: Paginated change feed with `since_id` auto-refresh, `ETag`, and multi-criteria filters.
   - `POST /api/v1/changes/{change_id}/triage`: Authenticated triage workflow (`reviewed`, `flagged`, `reverted`).
   - `GET /api/v1/freshness`: Returns both data and live replication timestamps and age metrics.
   - `GET /api/healthz/live`: Healthcheck returning 503 if replication lag exceeds 2 hours.
6. **Testing & Build Verification:**
   - Added `tests/test_change_rules.py` (10 tests).
   - Added `tests/test_detect_changes.py` (5 tests).
   - Added `tests/test_changes_api.py` (6 tests).
   - Pytest: 108 passed.
   - Vitest: 62 passed across 7 test suites.
   - ESLint: 0 errors, 0 warnings.
   - Vite: clean production build.

### 16.2 Changes Workspace, CSP Hardening & Community Positive Loop (2026-10-30)
1. **Interactive `/changes` Workspace (`changes_view.js` & `index.html`):**
   - Added `Changes` workspace tab and full-featured table view for daily and live events.
   - Keyboard triage shortcuts:
     - `J` / `K` for moving selection.
     - `Enter` to inspect place on map.
     - `A` to acknowledge / review change (`POST /api/v1/changes/{id}/triage`).
     - `R` to flag change for revert.
     - `H` to open OSM object history on openstreetmap.org.
     - `C` to open OSMCha for the specific changeset (or bounding box).
     - `M` to open Osmose issues nearby.
     - `.` to flush and show incoming real-time changes without shifting cursor position.
   - 60s background polling with ETag caching and incoming changes notification pill.
2. **CSP Hardening (`deploy/Caddyfile.container` & `frontend/vite.config.js`):**
   - Added `https://osmose.openstreetmap.fr https://overpass-api.de` to `connect-src` allowing on-click browser queries as specified in §3.3.5 without relaxing security boundaries.
3. **Community Positive Loop (`community.html` & `community.js`):**
   - Added `#fixed-issues-container` displaying verified issue fixes (`flag=issue-fixed`) to celebrate community progress.
4. **Testing & Build Verification:**
   - Added `frontend/tests/changes_view.test.js` (5 unit tests).
   - Full Vitest suite: 67 passed across 8 test files.
   - Full Pytest suite: 108 passed.
   - ESLint: 0 errors, 0 warnings.
   - Vite: clean production build in 353 ms.

---

## 17. Redesign Phase 2b: Live Replicator & Freshness Metrics (2026-10-30)

Started Phase 2b from `REDESIGN.md` §3.3 & §5:

### 17.1 Completed Items
1. **Live Replication Engine (`pipeline/live_replicator.py`):**
   - Built lightweight daemon for `manara-live` Coolify resource streaming OSM minutely replication diffs.
   - State polling via `state.txt`, 3-tier sequence path formatting (`006/123/456.osc.gz`), sequential diff parsing.
   - Strict privacy boundary: drops `user` and `uid` while parsing XML, keeping only `changeset`.
   - Filters to Saudi Arabia bounding box (`SA_BBOX`) and matches against canonical `is_worship_tagged`.
   - Writes live change events to `change_events` (`source = 'live'`) and updates `replication_state`.
2. **Dual Topbar Freshness Labels (`frontend/index.html` & `frontend/src/app.js`):**
   - Added semantic `<time>` elements for both **مباشر / Live** and **بيانات / Data** indicators.
   - Automated 60s background polling from `/api/v1/freshness` and window focus refresh.
   - Relative compact formatting ("now", "5m", "20h", "3d" / "الآن", "5 د", "20 س", "3 ي") reusing `timeago.js`.
3. **Privacy Policy Formalization (`frontend/privacy.html`):**
   - Updated both Arabic and English privacy policy sections explicitly documenting the retention of changeset IDs for quality assurance while confirming mapper identities and user IDs from replication diffs are never logged or stored.
4. **Schema Expansion (`backend/app/schema.py`):**
   - Added `live_places` and `live_pending` tables for unconfirmed real-time geometries.
5. **Testing & Verification:**
   - Added `tests/test_live_replicator.py` (6 unit tests).
   - Pytest: 114 passed.
   - Vitest: 67 passed across 8 test files.
   - ESLint: 0 errors, 0 warnings.
   - Vite: clean production build in 395 ms.

---

## 18. Redesign Phase 3: Tag Directory Collections & Live Tag Stats (2026-10-30)

Started Phase 3 from `REDESIGN.md` §3.2, §4.6 & §5:

### 18.1 Completed Items
1. **Saudi Tagging Directory Schema (`content/tags/*.yaml`):**
   - Created 13 canonical YAML tag documents covering Saudi places of worship (`amenity=place_of_worship`, `building=mosque`, `building=yes`, `religion=muslim`, `denomination=sunni`, `denomination=shia`, `denomination`, `name`, `name:ar`, `name:en`, `female`, `wheelchair`, `capacity`).
   - Each entry follows the `TagDoc` schema: localized Arabic/English labels, Saudi-specific mapping notes, good and bad examples with explanations, rule linkages, and OSM wiki links.
   - Cross-platform file naming avoided Windows NTFS alternate stream reserved characters (colons).
2. **Tag Usage Pipeline & Statistics Engine (`pipeline/tag_stats.py`):**
   - Counts tag and key usage, percentages, and `with_key` co-occurrence matrices for places of worship.
   - Outputs atomic `tag_stats_sa.json` and precompiled `tags.json` merged with live `usage_sa` metrics.
   - Supports upserting historical trends into the `tag_usage_history` table in PostgreSQL.
   - Integrated into `pipeline/run.py` (`STEPS` and `PUBLISHED_FILES`), root `Dockerfile`, and `frontend/vite.config.js`.
3. **Database Schema Expansion (`backend/app/schema.py`):**
   - Added `tag_usage_history` table with unique constraint on `(dataset_version, tag_key, tag_value)` and indexing for fast tag trend queries.
4. **CI Rule Linkage Check (`tests/test_tags.py`):**
   - Enforced bidirectional integrity: every single validation rule in `RULE_IDS` (`missing_amenity`, `missing_name`, `missing_name_en`, `missing_denom`, `size_too_small`, `size_too_large`, `stale_data`, `building_yes`, `mapped_as_node`, `ml_geometry_anomaly`, `duplicate_poi`, `outdated_tags`, `qibla_deviation`) is covered by at least one tag page, and all referenced rules exist.
   - Schema validation ensures valid statuses, OSM types, and localized labels.
5. **Astro Integration:**
   - Installed Astro (`astro v7.4.4`) in `frontend/`.
6. **Testing & Verification:**
   - Added `tests/test_tags.py` (4 tests) and `tests/test_tag_stats.py` (2 tests).
   - Pytest: 120 passed (up from 114).
   - Vitest: 67 passed across 8 test suites.
   - ESLint: 0 errors, 0 warnings.
   - Vite: clean production build in 219 ms.

### 18.2 Phase 3 Step 2: Searchable Tag Directory Workspace (`/tags`)
1. **Interactive Tag Directory (`frontend/tags.html` & `frontend/src/tags.js`):**
   - Built full Tag Directory workspace matching [`REDESIGN.md` §3.2 & §4.6](file:///c:/Users/abdul/Desktop/GCC20260707/REDESIGN.md#L671).
   - Renders each tag entry with key/value pills, status badges (`approved` / `discouraged`), `applies_to` targets (`node`, `way`, `relation`), and bilingual labels.
   - Saudi Mapping Guidelines callout (`saudi_notes`) highlighting local practices.
   - Live Saudi usage statistics (counts, percentages, and top 5 co-occurring tags from `tags.json` and `tag_stats_sa.json`).
   - Good vs bad examples with explanatory `why` callouts.
   - Direct QA rule cards linking into the QA workspace (`/qa?rule=<id>`).
   - Embedded UNGEGN/GASGI Arabic-to-English transliteration tool for `name:en` with instant copy-to-clipboard.
   - External links for opening iD editor with preset preselected, Overpass Turbo scoped to Saudi Arabia (`area["ISO3166-1"="SA"]`), and official OSM Wiki pages.
2. **Arabic-Normalized Instant Search & Filtering:**
   - Powered by `ArabicText.normalize()` in `frontend/src/arabic.js`, seamlessly matching queries across key, value, Arabic/English labels, Saudi notes, and rule IDs (resilient to alef/hamza/taa marbuta variations).
   - Filter chips: `All`, `Approved`, `Discouraged`, `Core Worship`.
   - Global keyboard shortcuts: `/` focuses search bar; `Esc` clears search.
   - URL hash deep linking: navigation to `#tag-slug` smoothly scrolls and highlights target card.
3. **AppShell & Navigation Integration:**
   - Added `Tags` navigation tab to TopBar in `frontend/index.html`.
   - Added `Tags` link to footer and Command Palette (`frontend/src/palette.js` and `frontend/src/app.js`).
   - Added quick links in `frontend/community.html`.
   - Registered `tags.html` entrypoint in `frontend/vite.config.js`.
4. **Testing & Verification:**
   - Added `frontend/tests/tags.test.js` (6 unit tests).
   - Vitest: 73 passed across 9 test suites (up from 67).
   - Pytest: 120 passed.
   - ESLint: 0 errors, 0 warnings.
   - Vite: clean production build in 225 ms.

### 18.3 Phase 3 Step 3: Beginner Onboarding (`/start`) & Guides (`/guides`) — Phase 3 Complete
1. **Curated Documentation Guides (`content/guides/*.md` & `frontend/guides.html`):**
   - Authored 4 comprehensive bilingual guides matching [`REDESIGN.md` §3.2 & §5 Phase 3](file:///c:/Users/abdul/Desktop/GCC20260707/REDESIGN.md#L795):
     - `names-and-transliteration.md`: Default Arabic naming, Jami' (Grand Mosque) vs Masjid (Mosque), UNGEGN/GASGI transliteration standards, omission of pious honorifics.
     - `outlines-vs-nodes.md`: Merging POI nodes into building outlines (`building=mosque`), avoiding duplicate POIs (`duplicate_poi`), and when standalone nodes remain appropriate (indoor musallas in multi-purpose complexes).
     - `josm-setup.md`: 1-minute setup instructions for JOSM Remote Control on localhost port `8111` with one-click editing.
     - `review-etiquette.md`: Constructive community collaboration, high-resolution imagery verification, and descriptive changeset comments.
   - Built [`frontend/guides.html`](file:///c:/Users/abdul/Desktop/GCC20260707/frontend/guides.html), [`frontend/src/guides.js`](file:///c:/Users/abdul/Desktop/GCC20260707/frontend/src/guides.js), and [`frontend/src/styles/guides.css`](file:///c:/Users/abdul/Desktop/GCC20260707/frontend/src/styles/guides.css).
2. **Beginner 3-Step Onboarding Wizard (`frontend/start.html` & `frontend/src/start.js`):**
   - Built `/start` beginner path per [`REDESIGN.md` §1.3](file:///c:/Users/abdul/Desktop/GCC20260707/REDESIGN.md#L90):
     - **Step 1:** Sign in with OpenStreetMap (OAuth PKCE check via `OsmApi`, verified status badge).
     - **Step 2:** Curated easy queue for `missing_name_en` where Arabic name is known; automated UNGEGN transliteration suggestion with inline editable input, tag diff preview (`+ name:en = ...`), 1-click submit via `OsmApi` or fallback edit in iD, and skip navigation.
     - **Step 3:** Celebration banner with direct action links to `/tags#tag-name_en` and the main QA workspace (`/qa`).
3. **AppShell & Navigation Integration:**
   - Added `Start Here` and `Guides` to footer links in `frontend/index.html`.
   - Added actions to Command Palette in `frontend/src/palette.js` and `frontend/src/app.js`.
   - Registered `guides.html` and `start.html` entrypoints in `frontend/vite.config.js`.
4. **Testing & Build Verification:**
   - Added `frontend/tests/start_guides.test.js` (4 tests).
   - Full Vitest suite: 77 passed across 10 test files.
   - Full Pytest suite: 120 passed.
   - ESLint: 0 errors, 0 warnings.
   - Vite: clean production build in 712 ms across all 7 HTML pages (`index.html`, `qa`, `changes`, `tags.html`, `start.html`, `guides.html`, `about.html`, `privacy.html`, `community.html`).

**Phase 3 is now 100% COMPLETE.** Next phase in roadmap is **Phase 4: Task Tracker & Sprints**.

---

## 19. Redesign Phase 4: Local Task Tracker & Sprints API (2026-10-30)

Started Phase 4 from `REDESIGN.md` §3.1, §4.2, §4.7 & §5:

### 19.1 Phase 4 Step 1: Database Schema & Sprints Concurrency Engine
1. **Database Schema Expansion (`backend/app/schema.py`):**
   - Added `sprints` table: stores area (region code or polygon), theme, rule IDs, urgency threshold, hashtag, dates, status (`draft`/`active`/`closed`), admin creator, and progress summary.
   - Added `sprint_tiles` table: 0.02° grid cells (~2.2 km blocks) matching `calculate_gaps.py` 5x5 block aggregation. Features optimistic concurrency `rev`, states (`ready`, `mapping`, `mapped`, `validating`, `validated`, `invalidated`, `skipped`), lock TTL (2h), `lock_uid`, `lock_display_name`, `lock_kind`, `lock_expires_at`, `mapped_by`, `validated_by`, and `workload`.
   - Added `tile_events` table: append-only audit trail logging all state transitions, reasons, notes, and user UIDs.
2. **Sprints Concurrency & Management API (`backend/app/routers/sprints.py`):**
   - `GET /api/v1/sprints`: lists sprints with computed progress summary (`total`, `by_state`, `workload_remaining`, `percent_complete`).
   - `POST /api/v1/sprints`: admin-only sprint creation with area bounding (validates area <= 5,000 km², tiles <= 2,000) and automated 0.02° tile generation.
   - `GET /api/v1/sprints/{slug}`: sprint metadata and progress.
   - `PATCH /api/v1/sprints/{slug}`: admin-only partial update (title, instructions, status, dates, hashtag).
   - `GET /api/v1/sprints/{slug}/tiles`: compact tile array with `ETag: W/"<rev_max>"` supporting 304 Not Modified caching for 60s background polling.
   - `PUT /api/v1/sprints/{slug}/tiles/{tile_id}`: atomic state transitions (`lock`, `release`, `done`, `approve`, `invalidate`, `skip`, `reopen`):
     - **Optimistic Concurrency:** checks `If-Match: rev`; returns `409 Conflict` on concurrent collisions.
     - **Self-Validation Rejection:** returns `403 Forbidden` if a mapper attempts to validate their own tile (`mapped_by == user.osm_uid`).
     - **Lock TTL & Auto-Expiry:** 2-hour lease with lazy expiration returning stale locks to previous stable state.
     - **Active Locks Cap:** enforces maximum 3 active simultaneous locks per user.
   - `GET /api/v1/sprints/{slug}/maproulette`: exports sprint tasks as a valid MapRoulette challenge GeoJSON FeatureCollection.
3. **Integration & Test Verification:**
   - Registered `sprints.router` in `backend/app/main.py`.
   - Added `tests/test_sprints_api.py` (10 unit & concurrency tests).
   - Pytest: 130 passed (up from 120).
   - Vitest: 77 passed across 10 test files.
   - ESLint: 0 errors, 0 warnings.
   - Vite: clean production build in 374 ms.

### 19.2 Phase 4 Step 2: Task Tracker & Sprint Board UI, External Editors, ETag Polling & Testing
1. **Sprint Board UI & Modals (`frontend/tasks.html`, `frontend/src/tasks.js`, `frontend/src/styles/tasks.css`):**
   - Built list-first campaign overview and interactive grid board for sprint tiles.
   - Designed responsive tile status styling across the 7 states (`ready`, `mapping`, `mapped`, `validating`, `validated`, `invalidated`, `skipped`).
   - Inspector sidebar panel with tile state, locking user, mapper, validator, workload, and contextual action buttons.
   - Rejection modal for `invalidated` state capturing specific feedback reasons into `tile_events`.
   - Enforced client-side self-validation prevention: blocks peer validation actions if `currentUserUid === tile.mapped_by`.
2. **External Editor Integration & Shortcuts:**
   - Single-click launch into **iD editor** (`https://www.openstreetmap.org/edit?editor=id#map=16/lat/lon&comment=...&hashtags=...`).
   - Remote control integration into **JOSM** (`http://127.0.0.1:8111/load_and_zoom?left=...&bottom=...&right=...&top=...`).
   - Keyboard navigation shortcuts: `N` (next ready tile with highest workload), `L` (lock for mapping/validation), `D` (mark done), `A` (approve), `X` (invalidate), `S` (skip), `Esc` (deselect).
3. **Background ETag Polling & Navigation Wiring:**
   - Efficient 60s background tile polling with `If-None-Match: W/"<rev_max>"` receiving 304 Not Modified when idle.
   - Added `/tasks` route in `frontend/vite.config.js` and topbar tab navigation in `frontend/index.html`.
   - Wired Command Palette action `{ id: 'tasks', ... }` in `frontend/src/palette.js` and `frontend/src/app.js`.
4. **Decoupled Architecture & Testing (`frontend/src/tasks_view.js`, `frontend/tests/tasks_view.test.js`):**
   - Extracted pure helper functions into `tasks_view.js` (`generateIdEditorUrl`, `generateJosmRemoteUrl`, `findNextReadyTile`, `formatTileStateBadge`, `calculateSprintProgress`).
   - 10 unit tests covering URL generation, bounding calculations, workload priority selection, and progress metrics.
   - Vitest: 87 passed across 11 test suites.
   - ESLint: 0 errors, 0 warnings.
   - Vite: clean build in 263 ms.

### 19.3 Phase 4 Step 3: Pipeline Workload Computation & Pending Refresh Engine
1. **Automated Sprint Tile Workload Ingestion (`pipeline/load_db.py`):**
   - Added `update_sprint_workloads(conn)` executed atomically right after staging table production swap.
   - For all active or draft sprints, queries spatial boundaries via `ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326)`.
   - Aggregates issues from `issues` matching `sprint.rule_ids` (if configured) joined with `places` spatial containment.
   - Aggregates coverage gaps from `gaps` exceeding `sprint.gap_min_urgency` (if configured).
   - Writes computed sum `workload = issue_count + gap_count` to each tile in `sprint_tiles`.
2. **Pending Refresh Lifecycle Management:**
   - Detects verified edits in `edits` created after the latest dataset `published_at` timestamp.
   - Sets `pending_refresh = TRUE` for any tile intersecting an edited place; clears back to `FALSE` as new daily Geofabrik extracts are published.
3. **Automated Verification:**
   - Authored test suite `tests/test_sprint_workload.py` covering missing tables, empty active sprints, and query execution for workload and pending refresh.
   - Pytest: 134 passed (up from 130).
   - Vitest: 87 passed across 11 test suites.

**Phase 4 is now 100% COMPLETE.** Next phase in roadmap is **Phase 5: Data Hub & Vector Overlays (PMTiles & MapLibre)**.

---

## 20. Redesign Phase 5: Data Hub & Vector Overlays (2026-10-30)

Started Phase 5 from `REDESIGN.md` §3.6, §4.6 & §5:

### 20.1 Phase 5 Step 1: Open Data Hub Manifest Engine & `/data` Workspace
1. **Data Manifest & Tabular Exporters Engine (`pipeline/build_data_hub.py`):**
   - Automatically generates `manifest.json` conforming to `REDESIGN.md` §4.6 (`DataManifest`).
   - Exports CSV tabular data with UTF-8 BOM alongside GeoJSON for places (`places_of_worship_sa.csv`), coverage gaps with coordinate conversion (`worship_gaps_sa.csv`), and suggestions (`suggested_mosques_sa.csv`).
   - Computes exact file sizes, SHA-256 hashes, and feature counts.
   - Embeds pre-configured Overpass Turbo queries for Saudi mosques, unnamed places, missing English names, and `building=yes` corrections.
   - Integrated `build_data_hub.py` into `pipeline/run.py` pipeline sequence and published files catalog.
2. **Data Hub Frontend Workspace (`frontend/data.html`, `frontend/src/data.js`, `frontend/src/styles/data.css`):**
   - Clean glass design displaying version metadata, ODbL 1.0 license compliance, and dataset attribution.
   - Instant search and dual filtering by layer (Places, Gaps, Suggestions, Boundary) and format (GeoJSON, CSV).
   - One-click copy for SHA-256 digests with visual toast confirmation.
   - Interactive Overpass Turbo preset cards with direct execution links into `overpass-turbo.eu`.
3. **App Navigation & Routing Integration:**
   - Added `/data` clean URL route in `frontend/vite.config.js`.
   - Wired Topbar navigation tab and footer site links in `frontend/index.html`.
   - Added Command Palette action `data_hub` in `frontend/src/palette.js` and `frontend/src/app.js`.
4. **Automated Test Verification:**
   - Authored `tests/test_data_hub.py` (5 unit tests covering SHA-256 hashing, CSV exporters, and manifest schema).
   - Authored `frontend/tests/data_view.test.js` (10 unit tests covering bytes formatting, hash badges, Overpass URLs, and multi-criteria filtering).
   - Pytest: 139 passed (up from 134).
   - Vitest: 97 passed across 12 test suites (up from 87).
   - ESLint: 0 errors, 0 warnings.
   - Vite: clean production build in 287 ms.

### 20.2 Phase 5 Step 2: PMTiles Vector Overlay Builder & HTTP Range Serving
1. **PMTiles Vector Overlay Builder (`pipeline/build_overlays.py`):**
   - Implemented automated building of `places.pmtiles`, `gaps.pmtiles`, and `suggestions.pmtiles` conforming to PMTiles v3 specification.
   - Trims `places` properties to core metadata (`id`, `osm_type`, `osm_id`, `name`, `name_en`, `religion`, `denomination`, `building`, `amenity`), reducing transfer payload for mobile rendering.
   - Integrates with `tippecanoe` when available; provides a compliant fallback PMTiles v3 archive with exact 127-byte header and gzip-compressed JSON metadata for environments without native tippecanoe binary.
   - Integrated `build_overlays.py` into `pipeline/run.py` sequence and updated `pipeline/Dockerfile`.
2. **HTTP Range Request Serving (`frontend/vite.config.js`):**
   - Added `'places.pmtiles'`, `'gaps.pmtiles'`, `'suggestions.pmtiles'` to `DATA_FILES`.
   - Added HTTP 206 Partial Content Range serving with `Accept-Ranges: bytes` and `Content-Range: bytes start-end/size` in dev/preview server middleware.
3. **Automated Verification:**
   - Authored `tests/test_build_overlays.py` (3 tests verifying 127-byte PMTiles v3 header, gzip metadata parsing, and overlay generation).
   - Pytest: 142 passed (up from 139).
   - Vitest: 97 passed across 12 test suites.
   - ESLint: 0 errors, 0 warnings.
   - Vite: clean production build in 257 ms.
