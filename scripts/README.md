# Scripts Directory

Active scripts for Satellite AI mosque detection, active-learning synchronization with the VPS, dataset construction, and project maintenance.

## 1. Live Sweeper & VPS Sync
- **`ai_background_sweeper.py`**: Autonomous background radar scanning Saudi worship-coverage gap cells (Esri + Mapbox z19 patches) with `best_v5_obb.pt`, snapping roof boundaries, updating `poc_satellite_output/sweeper_live_dashboard.html`, and optionally publishing to the VPS. Run it with `python -u scripts/ai_background_sweeper.py --continuous --provider both` (see `--help` for the rest).
- **`scan_worship_gaps.py`**: Core patch fetching, Qibla-aligned rotation, coordinate conversion, and YOLO inference helpers used by the sweeper.
- **`publish_ai_detections.py`**: Syncs `ai_detected_mosques_sa.geojson` to the VPS (`app.ai_sync import` over SSH) and pulls community review tallies into `ai_site_reviews.json` and `active_learning_feedback.json`.
- **`stage2_verifier.py`**: Stage-2 feature prototype verifier (`verifier_prototypes.pt`).
- **`stage3_geometric_guard.py`**: Geometric, Qibla, area, and road-distance heuristics guard.
- **`roof_boundary_snapping.py`**: Contours & Qibla-aligned OBB roof footprint snapping.
- **`step1_1_generate_bboxes.py`**: Extracts ground-truth OSM mosque bounding boxes and satellite tile patches.
- **`phase5_active_learning.py`**: Local active-learning review server and feedback manager.
- **`apply_user_feedback.py`**: Applies `active_learning_feedback.json` verdicts to the live sweeper state and rebuilds overlays.

## 2. V5 Dataset & Evaluation
- **`build_dataset_v5.py`**: Builds the spatially split, de-biased YOLOv11-OBB V5 dataset (`poc_satellite_output/mosque_dataset_v5`).
- **`thin_empty_background_v5.py`**: Thins empty background patches in `mosque_dataset_v5` to balance positive/negative ratios.
- **`eval_detector_v5.py`**: Evaluates OBB detector weights on held-out `val` and `test` splits.
- **`eval_cascade_v5.py`**: Evaluates the full multi-stage detection cascade on `val` and `test` splits.
- **`make_train_v5_notebook.py`**: Generates the Colab training notebook (`poc_satellite_output/notebooks/train_v5_obb_colab.ipynb`).

## 3. Content & i18n Utilities
- **`build_transliteration_rules.py`**: Compiles Arabic-to-English transliteration rules into `content/transliteration_rules.json`.
- **`find_missing_i18n.py`**: Audits frontend source files for untranslated i18n keys.

## 4. Archive (`scripts/archive/`)
Historical V0–V4 dataset builders, one-off migration helpers, and ad-hoc inspection scripts are stored in `scripts/archive/`.
