#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="${BASE_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"

DASHBOARD_URL="${DASHBOARD_URL:-http://127.0.0.1:3000}"
API_HEALTH_URL="${API_HEALTH_URL:-http://127.0.0.1:8000/api/health}"
COUNTRY="${COUNTRY:-France}"
PRODUCT="${PRODUCT:-france_mavenclad_snowflake}"
YEAR="${YEAR:-2023}"
VERSION="${VERSION:-latest}"
DATA_SOURCE="${DATA_SOURCE:-snowflake}"
CAPTURE_SPEC_PATH="${CAPTURE_SPEC_PATH:-}"

RUN_TS="${RUN_TS:-$(date +%Y%m%d_%H%M%S)}"
RUN_DIR="${RUN_DIR:-$BASE_DIR/runs/$RUN_TS}"
MANIFEST_PATH="${MANIFEST_PATH:-$RUN_DIR/manifests/component_manifest.json}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
NODE_PATH="${NODE_PATH:-$BASE_DIR/node_modules}"
PRUNE_SCREENSHOTS_AFTER_EXPORT="${PRUNE_SCREENSHOTS_AFTER_EXPORT:-0}"

mkdir -p "$RUN_DIR/clean" "$RUN_DIR/manifests" "$RUN_DIR/docs" "$RUN_DIR/logs"

if [[ ! -d "$BASE_DIR/node_modules/playwright" ]]; then
  echo "Installing base dashboard-docs node dependencies..."
  (cd "$BASE_DIR" && npm install)
fi

echo "Checking API and dashboard availability..."
curl -sS "$API_HEALTH_URL" >/dev/null
curl -sS "$DASHBOARD_URL" >/dev/null

echo "Capturing deterministic screenshots + hotspot/component manifest..."
NODE_PATH="$NODE_PATH" \
RUN_DIR="$RUN_DIR" \
OUTPUT_DIR="$RUN_DIR/clean" \
MANIFEST_PATH="$MANIFEST_PATH" \
DASHBOARD_URL="$DASHBOARD_URL" \
API_HEALTH_URL="$API_HEALTH_URL" \
COUNTRY="$COUNTRY" \
PRODUCT="$PRODUCT" \
YEAR="$YEAR" \
VERSION="$VERSION" \
DATA_SOURCE="$DATA_SOURCE" \
CAPTURE_SPEC_PATH="$CAPTURE_SPEC_PATH" \
node "$BASE_DIR/scripts/capture_dashboard_interactive_hotspots_playwright.mjs" \
  | tee "$RUN_DIR/logs/capture_interactive.log"

echo "Preparing interactive site source + manifests..."
"$PYTHON_BIN" "$BASE_DIR/scripts/build_interactive_walkthrough.py" \
  --run-dir "$RUN_DIR" \
  --manifest "$MANIFEST_PATH" \
  --stage prepare \
  | tee "$RUN_DIR/logs/prepare_interactive.log"

echo "Building static interactive walkthrough..."
(cd "$RUN_DIR/interactive-site-src" && npm install && npm run build) \
  | tee "$RUN_DIR/logs/build_interactive_site.log"

echo "Finalizing static export + QA + open wrapper..."
"$PYTHON_BIN" "$BASE_DIR/scripts/build_interactive_walkthrough.py" \
  --run-dir "$RUN_DIR" \
  --stage finalize \
  | tee "$RUN_DIR/logs/finalize_interactive.log"

if [[ "$PRUNE_SCREENSHOTS_AFTER_EXPORT" == "1" ]]; then
  echo "Pruning screenshot-heavy artifacts..."
  "$BASE_DIR/scripts/prune_screenshot_artifacts.sh" "$RUN_DIR"
  echo "Note: screenshots were pruned; walkthrough must be regenerated to view image assets."
fi

echo
echo "RUN_DIR=$RUN_DIR"
echo "OPEN_REDIRECT=$RUN_DIR/docs/INTERACTIVE_WALKTHROUGH_OPEN.html"
echo "DIRECT_INDEX=$RUN_DIR/interactive-site-static/index.html"
