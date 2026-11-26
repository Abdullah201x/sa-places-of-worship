# Manara — Saudi Places of Worship Map

Interactive map, coverage-gap analysis, and QA/editing platform for places of worship in Saudi Arabia (`manara.saudiosm.org`). Python OSM `.pbf` pipeline + FastAPI/PostGIS backend + Vite/Leaflet/MapLibre frontend + satellite AI mosque detection.

## Hard rules
- Never read or open `.env`, `.env.*` (except `.env.example`), `*.pem`, `*.key`, `*.db`, `*.sqlite`, `*.pbf`, `*.pmtiles`, `*.geojson`, `*.csv`, `by-region/`, `ML/`, `scratch/`, `.pytest_cache/`, `.ruff_cache/`, `__pycache__/`, `frontend/dist/`, or `frontend/node_modules/`.
- Never read large generated root JSON data files (`places_of_worship_sa.*`, `suggested_mosques_sa.*`, `worship_gaps_sa.*`, `ai_detected_mosques_sa.*`, `mosque_anomalies.json`, `mosque_sizes.json`, `tag_stats_sa.json`, `active_learning_feedback.json`, `ai_site_reviews.json`, `summary.json`, `tags.json`).
- Never commit secrets, `.env`, certificates, or model weights. Keep personal notes out of tracked files (`docs/local_notes/` is gitignored).
- Keep shared QA and transliteration rules in sync: `content/qa_rules.json` and `content/transliteration_rules.json` are tested for parity across Python and frontend JS.

## Commands
- Python tests: `pytest -q -x --tb=short` (run targeted files or `-k` when iterating; CI runs with PostGIS via `MANARA_DATABASE_URL`)
- Backend dev: `cd backend && uvicorn app.main:app --reload --port 8010`
- Pipeline (single run): `python pipeline/run.py once` (or individual scripts under `pipeline/`)
- Frontend dev / build / lint / unit tests / smoke:
  - `cd frontend && npm run dev`
  - `cd frontend && npm run build`
  - `cd frontend && npm run lint`
  - `cd frontend && npm test`
  - `cd frontend && npm run smoke`

## File map
- See `docs/PROJECT_MAP.md` before searching for where things live.

## Layout
- `pipeline/` OSM `.pbf` extraction, gap grid, Qibla/geometry anomalies, PMTiles & data-hub builders, validation
- `backend/` FastAPI service (`app/main.py`, `app/routers/`, `app/templates/`, `migrations/`)
- `frontend/` Vite multi-page app (`src/`, `tests/`, `e2e/`, `public/`)
- `scripts/` Satellite AI sweeper, V5–V7 dataset/training/eval utilities, i18n/transliteration builders
- `content/` Shared rules (`qa_rules.json`, `transliteration_rules.json`), guides, and tag definitions
- `tests/` Python `pytest` suite covering pipeline, backend API, migrations, and rule parity
- `deploy/` Production `Caddyfile.container`

## Working style
- Reply concisely with the change or direct answer; do not restate the task.
- Make the smallest change that fits; add or update tests for rule, API, or UI behavior changes.
- Run only relevant tests unless full-suite verification is needed.
