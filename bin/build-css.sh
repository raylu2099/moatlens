#!/bin/bash
# Build Tailwind CSS → web/static/css/tailwind.min.css.
#
# Run manually whenever a new Tailwind class is introduced to a template
# (compilation is content-aware: classes not referenced by templates are
# purged). The committed output is what the server serves — Node is NOT
# required on NAS / in the container.
#
# Usage:  bin/build-css.sh
# Requires: npx (Node ≥ 18); tested with tailwindcss@3.4.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "${PROJECT_DIR}"

INPUT_CSS="$(mktemp -t moatlens-tw.XXXXXX).css"
trap 'rm -f "${INPUT_CSS}"' EXIT

cat > "${INPUT_CSS}" <<'EOF'
@tailwind base;
@tailwind components;
@tailwind utilities;
EOF

OUT="web/static/css/tailwind.min.css"
mkdir -p "$(dirname "${OUT}")"

echo "[build-css] pinning tailwindcss@3.4 via npx …"
npx --yes tailwindcss@3.4 \
    -c tailwind.config.js \
    -i "${INPUT_CSS}" \
    -o "${OUT}" \
    --minify

SIZE_KB="$(du -k "${OUT}" | cut -f1)"
echo "[build-css] wrote ${OUT} (${SIZE_KB} KB)"
