# Manara (manara.saudiosm.org): project handoff

This document summarises the plan to turn the site from a static GitHub Pages app into a real web app on a VPS: what's done, what's in progress, and what's next. It was written at the end of a Claude Code session on 2026-10-28 so another assistant can continue the work.

Repo: `github.com/Abdullah201x/sa-places-of-worship`. Coolify deploys from branch `main`. Local checkout: `C:\Users\abdul\Desktop\GCC20260707`.

---

## 1. What the project is

Manara is an interactive Leaflet map of places of worship in Saudi Arabia, built from OpenStreetMap data. The UI is Arabic (RTL) by default, with an English toggle. It has three modes:
- POI density;
- coverage gaps;
- a data-improvement mode for mappers: issue detection, a review queue, exports, and in-app tag fixes through the OSM API with OAuth2 PKCE.

A Python pipeline (osmium, shapely, scikit-learn) turns an OSM `.pbf` extract into these JSON datasets:

| File | Contents |
|---|---|
| `summary.json` | Counts, `updated_at` (also the frontend's cache-busting version), `pbf_date` |
| `places_of_worship_sa.geojson` | About 14k places |
| `worship_gaps_sa.json` | Gap grid |
| `sa_boundary.geojson` | Country boundary |
| `mosque_sizes.json` | Footprint areas |
| `mosque_anomalies.json` | ML anomaly flags and Qibla deviation |
| `suggested_mosques_sa.geojson` | About 54k Wikidata suggestions, from `osm-x-wikidata/data/sa.json` |

Until now, a desktop updater (`C:\Users\abdul\Desktop\update osm\update_projects.py`) ran the pipeline on Windows and committed the data files to git.

---

## 2. Hard constraints (must respect)

### VPS
See `VPS_HARDWARE_ANALYSIS.md`.
- 2 vCPU (AMD EPYC Genoa), 3.8 GiB RAM (about 2.3 GiB free), 2 GiB swap, 106 GiB free disk, Debian 13.
- It runs **Coolify 4.5**, and **Traefik (`coolify-proxy`) owns ports 80/443**. There is no host Caddy or nginx. Never bind host ports 80/443.
- It also hosts **rahmahealth.net**. Don't touch Rahma's containers.
- Keep Manara separate from Rahma. The one exception, which the user chose: Manara uses the **shared Umami** (v3.0.3, `analytics.rahmahealth.net`) as its own website, ID `401cdcc1-cbfb-4962-8fc7-9d906f900bff`.

### Memory caps
- The pipeline container is limited to `cpus: 1.5` and `memory: 1536M`, and must **never exceed 2 GiB**.
- PostGIS, when added, should be about 512M with `shared_buffers=128MB`.

### OSM compliance (the user is explicit about this)
- **No bulk reads from api.openstreetmap.org, ever.**
- Bulk data comes only from **Geofabrik's public** GCC extract (`https://download.geofabrik.de/asia/gcc-states-latest.osm.pbf`):
  - downloaded **once**;
  - then kept current with Geofabrik's **daily diffs** using `pyosmium-up-to-date`.
- The public extract drops `user`, `uid` and `changeset`, but keeps `version` and `timestamp`.
  - The app only uses the dropped fields for the "last edited by / UID / changeset" rows in the details panel (`frontend/src/app.js` around lines 1730–1770).
  - Those rows will be **fetched lazily**: one `GET /api/0.6/{type}/{id}.json` from the **user's own browser**, only when a logged-in mapper opens a place, cached in `sessionStorage` by type, id and version. No prefetching.
- Server-side OSM writes (Phase 4) must:
  - send User-Agent `Manara/1.0 (+https://manara.saudiosm.org)`;
  - respect 429 `Retry-After`;
  - apply per-user limits (about 10 changesets per hour, at most 50 objects per changeset);
  - always close changesets;
  - never offer a "fix all".
- Map tiles come from Esri and CARTO only, never `tile.openstreetmap.org`.
- GeoDesk was evaluated and rejected: GOL files don't store `version` or `timestamp`, and the app needs both.

---

## 3. Phase 1: DONE and live on manara.saudiosm.org

### Frontend
- **Vite app in `frontend/`**:
  - `index.html` (the map), plus `about.html` and `privacy.html` (bilingual; both languages are in `[data-lang]` blocks, and the shared i18n module handles the toggle).
  - `src/` holds ES modules: `main.js` (entry), `app.js`, `i18n.js`, `translations*.js`, `arabic.js`, `review.js`, `exporters.js`, `osm_api.js`, `editing.js`, `analytics.js`, `page.js`, `leaflet-setup.js`.
  - `vendor/BoundaryCanvas.js` is pinned to commit `83e6a72`.
  - The two cross-file assignments became setters: `setCurrentSearchQuery` and `setHideReviewedPlaces`.
- **Everything is self-hosted:** Leaflet, markercluster and leaflet.heat come from npm, and the fonts from `@fontsource-variable/*`. No CDN, no Google Fonts.
- **`vite.config.js`:**
  - `appType: 'mpa'`;
  - the dev server runs over HTTPS on port 8000 (OSM OAuth needs HTTPS);
  - a dev/preview middleware serves only the allowlisted dataset names under `/data/` (from `MANARA_DATA_DIR`, default the repo root), plus clean URLs `/about` and `/privacy`;
  - `npm run preview` sends the production CSP, read from `deploy/Caddyfile.container`.
- **Two build gotchas, both fixed:**
  - `cssMinify: 'esbuild'`: Lightning CSS drops the unprefixed `backdrop-filter` when the value uses `var()`, which kills the glass blur in Chrome.
  - `assetsInlineLimit` never inlines `.woff2` files, because the CSP is `font-src 'self'`.
- **Data URLs:** the frontend fetches `/data/<file>?v=<summary.updated_at>`.
- **Umami** (`src/analytics.js`):
  - The script is injected only when `VITE_UMAMI_WEBSITE_ID` is set, loaded as `/stats/script.js` with `data-host-url="/stats"`.
  - Delegated click events: mode switch, issue filter, export type, language toggle.
  - Code events: login success, fix uploaded (count only), note created.
  - Usernames are never sent.
- **ODbL:** attribution was added to the map's attribution control and to the MapRoulette GeoJSON export.
- **Removed:** `serve_ssl.py`, `server.py`, `tests/test_security.py`.

### Deployment
- **Root `Dockerfile`** (Coolify Dockerfile build pack, auto-deploys on push to `main`):
  1. Node 22 builds the frontend.
  2. Alpine pre-compresses dist and data (brotli q11 plus gzip -9).
  3. `caddy:2-alpine` serves on :80, with a `HEALTHCHECK` on `/healthz`.
- **`deploy/Caddyfile.container`:**
  - `admin off`, `auto_https off`, and `trusted_proxies static private_ranges` (Traefik is in front).
  - Security headers: HSTS, nosniff, Referrer-Policy, Permissions-Policy, and a strict **CSP** listing every external host the app uses.
  - Caching: `/data/*` is immutable when the request has `?v=` and `no-cache` otherwise; `/assets/*` is immutable; pages are `no-cache`; `try_files {path} {path}.html`; `precompressed br gzip`.
  - `/stats/script.js` and `/stats/api/send` **only** are proxied to `https://analytics.rahmahealth.net`, with `Host` rewritten, the visitor IP in `CF-Connecting-IP` and `True-Client-IP` (Traefik overwrites `X-Forwarded-For`), and cookies stripped. Everything else under `/stats` is a 404.
- **Coolify Traefik dynamic config `analytics-saudiosm.yaml`:** the user removed a `manara-stats-https` router that had been sending all of `/stats` to Umami and caused a blank dashboard page. It now only routes `analytics.saudiosm.org` to `http://10.0.2.2:3000`, which is the shared Umami.
- **GitHub Pages:** `404.html` plus `.nojekyll` redirect the old Pages URLs to manara.saudiosm.org.
- **Other files:** `.github/workflows/ci.yml` runs pytest, plus `npm ci`, lint and build. `.gitattributes` forces LF line endings for `*.sh` and `deploy/**`. `.dockerignore` keeps the build context small.

### Verified live
- All 14,017 places load, with no console errors.
- The only external host contacted is `server.arcgisonline.com`.
- The places file is served at 303 KB with brotli (7.4 MB raw).
- `.git`, `.py` files and the Dockerfile return 404.
- Analytics events arrive in Umami.

### Phase 1 commits on `main`
| Commit | Content |
|---|---|
| `11e1f6c` | Vite migration (user commit) |
| `d42781c` | Dockerfile and `Caddyfile.container` |
| `7351840` | Build fix |
| `197ebfc` | Umami proxy, pre-compression, consolidation |
| `98e61a9` | Proxy only the tracker endpoints |

---

## 4. Phase 2: IN PROGRESS (the server-side pipeline). Uncommitted local changes.

### Already done locally (not committed)
1. **`git mv` of the pipeline into `pipeline/`:** `common.py`, `extract_sa_boundary.py`, `extract_places.py`, `calculate_gaps.py`, `calculate_mosque_sizes.py`, `detect_geometry_anomalies.py`, `import_wikidata_suggestions.py`, `validate_data.py`, `requirements.txt`.
2. **`pipeline/common.py`:**
   - `CODE_DIR` is the script folder.
   - `BASE_DIR` is now the **data dir**: `MANARA_DATA_DIR`, defaulting to the repo root, so local behaviour is unchanged.
   - `extract_sa_boundary.py` and `import_wikidata_suggestions.py` now import `BASE_DIR` from `common` instead of defining their own.
3. **`import_wikidata_suggestions.py`:** the source is `--source`, else the `MANARA_WIKIDATA_SOURCE` env var, else `find_source()`.
4. **`validate_data.py`:** the "previous summary" comes from the `MANARA_PREVIOUS_SUMMARY` file when set (on the server, the published `current/summary.json`), else `git show HEAD:summary.json`.
5. **Test and CI paths:** `pytest.ini` has `pythonpath = pipeline`, and `ci.yml` installs from `pipeline/requirements.txt`. `pytest` passes (35 tests).
6. **New `pipeline/run.py`, the server runner (written, NOT yet tested):**
   - Commands: `python run.py once [--force]` and `python run.py schedule` (daily at `MANARA_RUN_AT_UTC`, default `23:30`, which is 02:30 Riyadh; it runs immediately if nothing has been published yet).
   - **Extract:** the first run downloads the public extract to `$MANARA_STATE_DIR/gcc-states.osm.pbf`. Later runs use `pyosmium-up-to-date -v --tmpdir`. That tool returns 0 both for "updated" and "no new data", so the runner detects a change by comparing the header's `osmosis_replication_sequence_number` before and after. It stops early if nothing changed (unless `--force`, or nothing has been published yet).
   - **Wikidata:** downloads `https://raw.githubusercontent.com/Abdullah201x/osm-x-wikidata/main/data/sa.json` with an ETag conditional GET. The URL was verified public (8.9 MB).
   - **Steps:** each runs as a subprocess in a fresh `$STATE/work`, with the env vars `MANARA_DATA_DIR`, `OSM_PBF`, `MANARA_WIKIDATA_SOURCE`, `MANARA_PREVIOUS_SUMMARY` and `PYTHONUNBUFFERED`. The boundary step runs with `--force`, and `validate_data.py` is last.
   - **Publish:** copies the 7 files plus `.br`/`.gz` into `$MANARA_PUBLISH_DIR/v<updated_at>/`, then atomically swaps a **relative** symlink `current -> v...`, keeps 2 versions, and writes `$STATE/status.json`. It uses a lock file (stale after 3 h).
   - **Needs:** the `brotli` pip package, plus `osmium` (which provides `pyosmium-up-to-date`).
7. **Measured peak memory** on the full 288 MB GCC extract (Windows, `psutil`). Scratch copy: `%TEMP%\manara-pipeline-measure`; results in `%TEMP%\measure.out`:

   | Step | Peak | Time |
   |---|---|---|
   | `extract_sa_boundary.py` | 873 MiB | 13 s |
   | `extract_places.py` | 894 MiB | 102 s |
   | `calculate_gaps.py` | 895 MiB | 77 s |
   | `calculate_mosque_sizes.py` | 872 MiB | 23 s |
   | `detect_geometry_anomalies.py` | **970 MiB (highest)** | 24 s |
   | `import_wikidata_suggestions.py` | 140 MiB | 2 s |
   | **Total** | | **about 4 min** |

   Conclusion: the highest peak is 970 MiB, which **fits the 1.5 GiB cap** with about 550 MiB to spare, so no restructuring is needed. If the data grows past about 1.3 GiB, either:
   - pass `idx='sparse_file_array,/state/nodes.idx'` to `apply_file(..., locations=True)` (keeps node locations on disk), or
   - clip the GCC extract to Saudi Arabia first with `osmium extract -p sa_boundary.geojson` (needs the `osmium-tool` apt package).
8. **Geofabrik facts:**
   - The public `gcc-states-updates/state.txt` uses the same sequence numbers as the internal feed (public 3867 vs local internal file 3866).
   - The local file's header points at the internal URL (`osm-internal.download.geofabrik.de`), so the server must start from a **public** download.

### Phase 2 Completed & Verified Live
1. **`pipeline/extract_places.py`**: removed `last_edited_by`, `user_id` and `changeset_id`; kept `version` and `edited_at`.
2. **Frontend lazy fetch**:
   - `OsmApi.fetchLastEdit(type, id, version)` implemented in `frontend/src/osm_api.js` with `sessionStorage` caching (`osm_meta:${type}/${id}@${version}`).
   - `showDetails` in `frontend/src/app.js` lazily loads contributor rows for authenticated mappers with race-condition selection guards. Guests remain under GDPR notice without network calls.
3. **`pipeline/Dockerfile`**:
   - Base `python:3.12-slim` + `libexpat1` + `pipeline/requirements.txt` + `brotli`.
   - Mounts `/state` (Docker volume `manara-state`) and `/published` (host mount `/data/manara/published`).
4. **Coolify setup**:
   - Created `manara-pipeline` container (ID `db86741a3c9a`) on VPS with `cpus: 1.5`, `memory: 1536M`, scheduled to run daily at 23:30 UTC.
5. **Web container dynamic serving**:
   - `deploy/Caddyfile.container` serves `/data/*` dynamically from `/srv/manara/published/current` with fallback to baked data.
   - Tested live: Brotli compression verified (`Content-Encoding: br`, 257 KB for 14k places).
6. **Execution & change detection verified**:
   - Initial run executed in 255s inside container, publishing `v20261027T232444Z` to `/data/manara/published`.
   - Second run correctly detected sequence 3867 was current: `"No new OSM data since the last run; nothing to do"`.
7. **Desktop updater retired**:
   - Removed `"gcc"` entry from `C:\Users\abdul\Desktop\update osm\update_projects.py`.
8. **README updated**:
   - `README.md` updated to reflect `pipeline/` directory, prerequisites, and automated runner options.

---

## 5. Phase 3: data API (FastAPI and PostGIS, read-only and public)

- **PostGIS** as its own Coolify database resource (image `postgis/postgis:16-3.4`, about 512M, `shared_buffers=128MB`), with migrations through Alembic.
- **Add `pipeline/load_db.py`** (run by `run.py` after validation). It loads the data into staging tables in one transaction and swaps them in:
  - `places(osm_type, osm_id, version, edited_at, tags jsonb, name, name_norm, name_en, religion, denomination, geom_type, geom, area_m2, anomaly_score, qibla_dev, region_code, dataset_id)`, with a GiST index on `geom` and a `pg_trgm` index on `name_norm`. `name_norm` is built with `common.normalize_arabic`, which matches `frontend/src/arabic.js`.
  - Also `gaps`, `suggestions`, `regions` (13 provinces, admin_level=4, from a new `extract_regions.py`), `dataset_versions`, and `region_stats_history` (a snapshot per run, for progress charts).
  - Each place gets a region assigned with `ST_Within`.
- **FastAPI service** (`backend/app/`): a Coolify app with a domain path or subdomain, about 200M. Caddy proxies `/api/*` to it on the Coolify network.
  - `GET /api/v1/meta`
  - `GET /api/v1/suggestions?bbox=&limit=` replaces the 11 MB suggestions download. It's only called in suggestions mode, above a minimum zoom.
  - `GET /api/v1/search?q=` (Arabic-aware)
  - `GET /api/v1/places/{type}/{id}`
  - `GET /api/v1/stats`, `/stats/regions`, `/stats/history`
  - `GET /api/healthz`
  - Pydantic validation, caps on bbox size and limit, slowapi rate limits, same-origin CORS only.
- Issue thresholds the user can adjust (size, Qibla) **stay in the browser**, applied to the compact places bundle.
- Add `/api` to the CSP's `connect-src` (already covered by `'self'`).

## 6. Phase 4: accounts and shared review

- **Server-side OSM OAuth2.** Register a new confidential app on osm.org with redirect `https://manara.saudiosm.org/auth/callback` and scopes `read_prefs write_api write_notes`. Endpoints: `/auth/login`, `/auth/callback` (code plus PKCE plus state), `POST /auth/logout`, `GET /api/v1/me`.
- **Identity** comes only from `user/details` on the server, never from client input. (The removed Flask attempt in commit `71db35d` trusted a `user_name` sent by the client. Don't repeat that.)
- **Tokens** are Fernet-encrypted in a `sessions` table. The cookie is `__Host-manara_session` (HttpOnly, Secure, SameSite=Lax).
- **Every write** checks the `Origin` header and requires an `X-Manara-CSRF` header.
- **Remove all token handling from `localStorage`** (`osm_api.js`, `app.js`).
- **Tables:** `users`, `sessions`, `review_marks` (unique per object, with user and version), `review_events`, `edits`, `batch_queue`.
- **`ReviewMarks`** (`review.js`) keeps its API but becomes server-backed, falling back to `localStorage` when the user is logged out.
- **Edit proxy** `POST /api/v1/osm/changesets`:
  - The server re-fetches each object, checks the version, and **allows only** the tag keys `amenity`, `building`, `name:en` and `denomination` (the quick fixes in `editing.js`).
  - It uploads, always closes the changeset, and records the edit.
  - Signed-in notes go through `POST /api/v1/osm/notes`; anonymous notes stay in the browser.
- **One-time import** of the existing `localStorage` marks and history after first login. Imported history doesn't count toward the leaderboard.
- **Backups:** a nightly `pg_dump` of the user tables, kept for 14 days and copied off-site.
- **Test against `master.apis.dev.openstreetmap.org` first.**

## 7. Phase 5: community and public pages

- **`/stats` page (Vite):**
  - per-region coverage, issues by type, progress over time from `region_stats_history`, and a recent-edits feed;
  - a leaderboard of server-recorded edits only, with an opt-out;
  - charts with uPlot or Chart.js, bilingual and RTL.
- **Note the path clash:** `/stats/*` is the Umami tracker path. Either use `/community` for this page, or move the tracker to another path such as `/a/`, updating both `analytics.js` and the Caddyfile.
- **Server-rendered pages** `/place/{type}/{id}` and `/region/{code}` (Jinja): OG tags, `Place` JSON-LD, `hreflang`, OSM attribution, and links to OSM/iD/JOSM.
- **`sitemap.xml` and `robots.txt`** regenerated each run. `robots.txt` already disallows `/stats/`.
- **Admin role** via an env allowlist of OSM uids. There is no pipeline-trigger endpoint.

## 8. Phase 6: operations

- CI already runs tests and the build. Coolify deploys on push to `main`.
- Monitoring:
  - `/healthz` (web);
  - `status.json`, which the API exposes as part of `/api/v1/meta`;
  - alert if the dataset is older than 3 days.
- Docker log rotation, pinned image tags, and backups (Phase 4).

---

## 9. Useful verification commands

```bash
# Frontend
cd frontend && npm ci && npx eslint src && npm run build && npx vite preview   # https://localhost:8000, production CSP

# Pipeline tests
python -m pytest -q

# Live checks
curl -s -o /dev/null -w '%{http_code}\n' https://manara.saudiosm.org/healthz        # 200
curl -s -o /dev/null -w '%{http_code}\n' https://manara.saudiosm.org/stats/login    # 404 (correct)
curl -sI -H 'Accept-Encoding: br' 'https://manara.saudiosm.org/data/places_of_worship_sa.geojson?v=x'  # Content-Encoding: br
```

A headless-browser smoke test was used before. It runs `playwright-core` with the local Chrome at `C:/Program Files/Google/Chrome/Application/chrome.exe` and checks:
- no console errors or CSP violations;
- markers appear at zoom 13 around Riyadh;
- the suggestions badge shows 54,508;
- CSV export works;
- the only external host is `server.arcgisonline.com`.

When testing against production, intercept `**/stats/api/send` so no fake visit is recorded.

## 10. Working preferences from the user

- Ask before outward-facing actions: pushing or merging to `main` deploys to production.
- Never risk an OSM block. State explicitly how each data-fetching feature complies.
- Keep Rahma and Manara separate, except for the shared Umami website.
