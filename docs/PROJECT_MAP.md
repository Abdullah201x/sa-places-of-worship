# Project Map

Quick "where is X?" index for Manara. Check here before running broad file searches.

## Root & Config
- `README.md`, `PRODUCT.md`, `DESIGN.md`, `SECURITY.md`, `LICENSE` — repository documentation
- `Dockerfile`, `deploy/Caddyfile.container` — production web + dataset Caddy image
- `.env.example` — environment variable template (never read `.env`)
- `pytest.ini` — pytest config (`testpaths = tests`, `pythonpath = pipeline`)
- `.github/workflows/ci.yml` — CI jobs (`pipeline-tests` with PostGIS, `frontend`, `smoke`)

## Data Pipeline (`pipeline/`)
- `pipeline/run.py` — orchestrates Geofabrik diff updates, staged execution, validation, and atomic publish
- `pipeline/common.py` — PBF lookup, centroids, Arabic normalization, atomic JSON writes, `summary.json`
- `pipeline/extract_sa_boundary.py`, `pipeline/extract_regions.py` — Saudi boundary & region polygons
- `pipeline/extract_places.py`, `pipeline/worship_tags.py`, `pipeline/tag_stats.py` — places of worship extraction & tag stats
- `pipeline/calculate_gaps.py`, `pipeline/calculate_mosque_sizes.py`, `pipeline/detect_geometry_anomalies.py` — gap grid, footprint area, Isolation Forest & Qibla deviation
- `pipeline/import_wikidata_suggestions.py` — Wikidata mosques missing from OSM
- `pipeline/live_replicator.py`, `pipeline/detect_changes.py`, `pipeline/change_rules.py`, `pipeline/load_db.py` — OSM replication, change detection, PostGIS loading
- `pipeline/build_overlays.py`, `pipeline/build_data_hub.py`, `pipeline/pmtiles_writer.py` — PMTiles & data-hub export builders
- `pipeline/validate_data.py` — pre-publish dataset sanity checks

## Backend (`backend/`)
- `backend/app/main.py` — FastAPI entrypoint, middleware, router mounting
- `backend/app/database.py`, `backend/app/schema.py`, `backend/migrations/` — PostGIS connection pool, schema, SQL migrations
- `backend/app/auth.py`, `backend/app/limiter.py` — OSM OAuth / session auth and rate limiting
- `backend/app/arabic.py`, `backend/app/transliteration.py`, `backend/app/ai_sync.py` — Arabic normalization, transliteration, VPS AI sync
- `backend/app/routers/` — API endpoints (`places.py`, `issues.py`, `search.py`, `stats.py`, `edits.py`, `reviews.py`, `changes.py`, `sprints.py`, `suggestions.py`, `ai_detections.py`, `community_data.py`, `auth.py`, `meta.py`, `seo.py`, `healthz.py`)
- `backend/app/templates/` — SSR SEO templates (`base_seo.html`, `place.html`, `region.html`)
- `backend/requirements.in`, `backend/requirements.txt` — direct & pinned dependencies

## Frontend (`frontend/`)
- HTML entry points: `index.html`, `mapgl.html`, `start.html`, `tasks.html`, `data.html`, `community.html`, `guides.html`, `tags.html`, `about.html`, `privacy.html`
- `frontend/vite.config.js`, `frontend/eslint.config.js`, `frontend/playwright.config.js`, `frontend/id-schema-plugin.js` — build, lint, Playwright config, iD tagging schema integration
- `frontend/src/main.js`, `frontend/src/app.js` — main dashboard entry & state wiring
- `frontend/src/map_kit.js`, `frontend/src/map_gl.js`, `frontend/src/map_gl_view.js`, `frontend/src/kit_gl.js` — Leaflet & MapLibre map engines
- `frontend/src/qa_view.js`, `frontend/src/validator.js`, `frontend/src/review.js`, `frontend/src/duplicate_inspector.js` — QA issues, review queue, duplicates
- `frontend/src/osm_api.js`, `frontend/src/editing.js`, `frontend/src/exporters.js`, `frontend/src/osmose.js` — OSM OAuth/API 0.6 editing & exports
- `frontend/src/i18n.js`, `frontend/src/translations.js`, `frontend/src/translations_static.js`, `frontend/src/arabic.js` — Arabic/English i18n & normalization
- `frontend/src/field_mode.js`, `frontend/src/focus_mode.js`, `frontend/src/gap_field.js`, `frontend/src/tasks_view.js`, `frontend/src/data_view.js`, `frontend/src/changes_view.js`, `frontend/src/ai_detections.js` — mode views
- `frontend/src/live_places.js` — live mosque delta merge (`/api/v1/places/live`), `LocalAdds`; plan in `docs/live-gap-updates-plan.md` (SQL write path: `backend/migrations/004_live_places_v2.sql`; replicator sync flag `MANARA_LIVE_PLACES_SYNC=1`)
- `frontend/src/styles/` — CSS modules (`tokens.css`, `index.css`, `mapgl.css`, etc.)
- `frontend/tests/` — Vitest unit tests; `frontend/e2e/` — Playwright smoke tests

## Scripts & Shared Content (`scripts/`, `content/`)
- `scripts/README.md` — guide to content/i18n maintenance scripts
- `scripts/build_transliteration_rules.py`, `scripts/find_missing_i18n.py` — content/i18n maintenance
- `content/qa_rules.json`, `content/transliteration_rules.json` — shared QA & transliteration rules
- `content/guides/`, `content/tags/` — guide and tag documentation content

## Tests (`tests/`)
- `tests/test_*.py` — pytest suite for pipeline, backend API, migrations, and Python/JS parity

## Large, Generated, or Sensitive Paths (Do Not Read)
- `.env`, `.env.*` (except `.env.example`), `*.pem`, `*.key`
- `*.osm.pbf`, `*.pbf`, `*.db`, `*.sqlite*`, `*.pmtiles`, `*.geojson`, `*.csv`, `*.pt`, `*.onnx`, `*.zip`
- `by-region/`, `ML/`, `poc_satellite_output/`, `Training results/`, `scratch/`, `docs/local_notes/`
- Root generated data JSONs: `places_of_worship_sa.*`, `suggested_mosques_sa.*`, `worship_gaps_sa.*`, `ai_detected_mosques_sa.*`, `mosque_anomalies.json`, `mosque_sizes.json`, `tag_stats_sa.json`, `active_learning_feedback.json`, `ai_site_reviews.json`, `summary.json`, `tags.json`
- Build/cache dirs: `frontend/dist/`, `frontend/node_modules/`, `frontend/playwright-report/`, `frontend/test-results/`, `test-results/`, `.pytest_cache/`, `.ruff_cache/`, `__pycache__/`
