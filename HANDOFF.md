# Manara (manara.saudiosm.org): Project Handoff

This document summarises the architecture, live infrastructure, completed phases (Phases 1–3 and Phase 6a), and upcoming roadmap (Phases 5, 4 and 6b) for **Manara** (`https://manara.saudiosm.org`), so another AI coding assistant can seamlessly continue the work.

**Where things stand:** Phases 1–3, Phase 4 (accounts & shared review), Phase 5a (`/community` page), Phase 5b (leaderboard, verified edits feed, and SEO pages), and Phase 6a (operations) are done. Phase 6b (final security review) remains. Nothing is half-finished in the code; `main` is clean.

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
| **Pipeline Worker** | `e3xakpyxk2xmq19aqpyvjdjq` (`manara-pipeline`) | `pipeline/Dockerfile` | None | `1.5 GiB` (`1.5 CPU`) | ~17 MiB idle (~970 MiB peak) | Runs `python run.py schedule` (daily 23:30 UTC / 02:30 Riyadh); mounts volume `manara-state:/state` and host `/data/manara/published:/published` |
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
5. **Phase 6b (NEXT):** final security review and verification.

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
  - Coolify scheduled backup on `manara-db`: database `manara`, frequency `daily` (00:00 UTC, 03:00 Riyadh, after the 23:30 UTC pipeline run), **14 days** local retention, no S3.
  - Files: `/data/coolify/backups/databases/root-team-0/manara-db-9uzoip4gqaxybg3e5oymh8sg/pg-dump-manara-*.dmp` (custom format, about 6.7 MB).
  - The scope is the **whole `manara` database**, not only the user tables (this replaced the earlier plan, because the user tables do not exist yet and the dump is small). Nothing needs changing when Phase 4 adds tables.
  - Verified: a manual `pg_dump -Fc` restored into a throwaway database with identical row counts (14,021 places, 59,695 gaps, 54,504 suggestions, 13 regions, 2 dataset versions), and Coolify's own dump lists all the data tables in `pg_restore -l`.
  - ⚠️ Risk the user accepted: losing the VPS disk loses the backups too. **Optional safety net:** a weekly manual `scp` of the newest dump to the desktop. Not set up.
- **Hygiene:**
  - Image tags pinned: `caddy:2.11-alpine` (changed), `node:22-alpine`, `alpine:3.22` and `python:3.12-slim` (already pinned), `postgis/postgis:17-3.5-alpine` (set in Coolify).
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
# 1. Run full Python test suite (72 tests: common, regions extractor, Phase 4/5b, transliteration NLP, FastAPI endpoints)
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
