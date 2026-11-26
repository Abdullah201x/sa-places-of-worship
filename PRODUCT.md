# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **OpenStreetMap Contributors & Local Mappers:** Mappers in Saudi Arabia and the GCC region improving cartographic coverage, fixing naming conventions, aligning footprints, and rectifying tagging anomalies.
- **Urban Planners & Spatial Analysts:** Researchers and municipal planners evaluating neighborhood coverage gaps where inhabited communities lack accessible places of worship.
- **GIS & Data Quality Engineers:** Operators validating geometry distortions, duplicate POIs, footprint area outliers, and Qibla orientation deviations.

## Product Purpose

Manara (منارة) is an interactive geospatial analytics platform and OSM data-improvement workspace for places of worship across Saudi Arabia. It visualizes mosque density, uncovers coverage gaps in road-dense populated sectors lacking places of worship, flags geometric and tagging anomalies, and provides an integrated, OAuth-authenticated editing environment to fix issues directly in OpenStreetMap.

## Positioning

Unlike generic map viewers or standard OSM tag checkers, Manara combines an offline Python data pipeline (daily Geofabrik diff processing, Isolation Forest geometry anomaly detection, and astronomical Qibla deviation calculation) with high-performance vector tiles (PMTiles), satellite AI detections, and an integrated, Arabic-first (RTL) editing workflow with OAuth 2.0 changeset authoring.

## Operating Context

- **Environment:** Desktop and mobile web browser interface, deployed via Docker/Caddy on VPS (Coolify) at `manara.saudiosm.org`.
- **Workflows:** Visualizing heatmaps and vector tiles, filtering by administrative region or anomaly type, inspecting individual mosque records, reviewing satellite AI suggestions, and committing changesets to OSM API 0.6.
- **Languages:** Primary interface in Arabic (RTL layout) with an English language switch.

## Capabilities and Constraints

- **Capabilities:**
  - Fast vector map rendering via MapLibre GL / Leaflet with PMTiles and raster basemaps (satellite, dark mode, street).
  - Coverage gap analysis with drivable road density weighted against mosque proximity (~440m grid cells).
  - Anomaly detection: building footprint area, geometric distortion (Isolation Forest), Qibla alignment deviation.
  - Interactive OSM review workflow: direct node/way editing, MapRoulette task generation, JOSM remote control, and Overpass export.
  - Satellite AI detection layers with active learning review flows.
- **Constraints:**
  - Web client performance must remain high even with tens of thousands of features (delegated to PMTiles).
  - Arabic typography and RTL spatial layout must be preserved without layout glitches.
  - Upstream OSM changes must be authenticated and conform to OSM tagging standards (`amenity=place_of_worship`, `religion=muslim`).

## Brand Commitments

- **Name:** Manara (خارطة المنارة لأماكن العبادة).
- **Typography:** Cairo Variable (`--font-title`, `--font-body`) for harmonious Arabic and Latin bilingual readability.
- **Palette:** Modern geospatial dark UI palette with cyan (`#00f2fe`) and electric emerald (`#00ff87`) accents, balanced on deep navy/slate backgrounds (`#0a0b10`).

## Evidence on Hand

- Pipeline code and tests in `pipeline/` and `tests/`.
- Over 60,000 places of worship indexed in `places_of_worship_sa.geojson` and `places.pmtiles`.
- Coverage gap grid in `worship_gaps_sa.json` and `gaps.pmtiles`.
- Machine learning anomaly models in `pipeline/detect_geometry_anomalies.py`.
- Production Vite frontend in `frontend/`.

## Product Principles

1. **Cartographic Precision Over Decorative Clutter:** The map and spatial data are primary; interface chrome supports rapid triage and visual clarity.
2. **First-Class Arabic RTL Experience:** Every component, control, and popup is built natively for Arabic RTL with natural bilingual flexibility.
3. **Respect Upstream OSM Truth:** Provide transparent reasoning for every flagged issue, cite evidence, and allow the contributor full authority over changesets.
4. **Resilient Performance:** Heavy compute belongs in the scheduled Python pipeline; the browser stays lightweight, snappy, and responsive.

## Accessibility & Inclusion

- Adherence to WCAG AA color contrast guidelines (4.5:1 text on dark backgrounds, 3:1 for large graphical accents).
- Keyboard-accessible map navigation, dialog focus rings, and explicit ARIA labels for bilingual screen readers.
- Respect `prefers-reduced-motion` for animated transitions and map panning.
