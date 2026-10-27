#!/usr/bin/env bash
# Deploys Manara on the VPS from the git checkout in /opt/manara:
#   1. pulls main,
#   2. builds the frontend in a throwaway Node container (no Node on the host),
#   3. publishes frontend/dist to /srv/manara/dist (old hashed assets are kept
#      for a while so open tabs keep working, then pruned),
#   4. publishes the datasets to /srv/manara/data (Phase 1: copied from the
#      repo; from Phase 2 the server-side pipeline writes them directly),
#   5. starts/updates the Docker stack.
#
# Usage:  sudo -u manara /opt/manara/deploy/deploy.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WEB_ROOT="${MANARA_WEB_ROOT:-/srv/manara}"
ENV_FILE="$REPO_DIR/deploy/.env"
COMPOSE=(docker compose -f "$REPO_DIR/deploy/docker-compose.yml" --env-file "$ENV_FILE")

DATA_FILES=(
  summary.json
  places_of_worship_sa.geojson
  worship_gaps_sa.json
  sa_boundary.geojson
  mosque_sizes.json
  mosque_anomalies.json
  suggested_mosques_sa.geojson
)

[ -f "$ENV_FILE" ] || { echo "Missing $ENV_FILE (copy deploy/.env.example)"; exit 1; }
# Only the build needs this value; read it without sourcing the whole file.
UMAMI_ID="$(grep -E '^VITE_UMAMI_WEBSITE_ID=' "$ENV_FILE" | cut -d= -f2- || true)"

echo ">> Updating the checkout"
git -C "$REPO_DIR" pull --ff-only

echo ">> Building the frontend"
docker run --rm \
  -u "$(id -u):$(id -g)" \
  -e HOME=/tmp \
  -e VITE_UMAMI_WEBSITE_ID="$UMAMI_ID" \
  -v "$REPO_DIR/frontend:/app" -w /app \
  node:22-alpine sh -c "npm ci --no-audit --no-fund && npm run build"

echo ">> Publishing the frontend"
mkdir -p "$WEB_ROOT/dist" "$WEB_ROOT/data"
# Assets first (hashed names, so nothing is overwritten), pages last, so a
# page never references an asset that isn't there yet.
rsync -a "$REPO_DIR/frontend/dist/assets/" "$WEB_ROOT/dist/assets/"
rsync -a --exclude assets/ "$REPO_DIR/frontend/dist/" "$WEB_ROOT/dist/"
find "$WEB_ROOT/dist/assets" -type f -mtime +30 -delete

echo ">> Publishing the datasets"
for f in "${DATA_FILES[@]}"; do
  # Copy then rename, so Caddy never serves a half-written file.
  install -m 0644 "$REPO_DIR/$f" "$WEB_ROOT/data/.$f.tmp"
  mv -f "$WEB_ROOT/data/.$f.tmp" "$WEB_ROOT/data/$f"
done

echo ">> Updating the Docker stack"
"${COMPOSE[@]}" pull --quiet
"${COMPOSE[@]}" up -d --remove-orphans

echo ">> Done. Check: curl -sI https://manara.saudiosm.org/ | head -n 5"
