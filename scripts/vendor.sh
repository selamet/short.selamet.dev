#!/usr/bin/env bash
# Downloads pinned front-end libraries into static/vendor (no CDN at runtime).
set -euo pipefail

HTMX_VERSION="${HTMX_VERSION:-2.0.8}"
CHARTJS_VERSION="${CHARTJS_VERSION:-4.5.1}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/static/vendor"
mkdir -p "$DEST"

curl -fsSL "https://cdn.jsdelivr.net/npm/htmx.org@${HTMX_VERSION}/dist/htmx.min.js" -o "$DEST/htmx.min.js"
curl -fsSL "https://cdn.jsdelivr.net/npm/chart.js@${CHARTJS_VERSION}/dist/chart.umd.js" -o "$DEST/chart.umd.js"
echo "htmx ${HTMX_VERSION}, chart.js ${CHARTJS_VERSION} → $DEST"
