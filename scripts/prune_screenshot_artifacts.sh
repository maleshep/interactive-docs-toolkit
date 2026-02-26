#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="${BASE_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
TARGET="${1:-$BASE_DIR/runs}"

if [[ ! -e "$TARGET" ]]; then
  echo "Target not found: $TARGET"
  exit 1
fi

echo "Pruning screenshot-heavy artifacts in: $TARGET"

find "$TARGET" -type d \
  \( -name clean -o -name annotated -o -path "*/interactive-site-src/public/screenshots" -o -path "*/interactive-site-static/screenshots" \) \
  -prune -print | while read -r d; do
    rm -rf "$d"
  done

find "$TARGET" -type f \
  \( -name "diagnostic_*.png" -o -name "diag_*.png" -o -name "*.jpg" -o -name "*.jpeg" \) \
  -print -delete

echo "Prune complete."
