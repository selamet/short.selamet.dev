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

# Strip sourcemap references: the .map files are not vendored, and an unresolved
# reference makes Django's collectstatic manifest post-processing fail.
sed -i.bak -e '/^\/\/# sourceMappingURL=/d' "$DEST/htmx.min.js" "$DEST/chart.umd.js" && rm -f "$DEST"/*.bak

echo "htmx ${HTMX_VERSION}, chart.js ${CHARTJS_VERSION} → $DEST"
