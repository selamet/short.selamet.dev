#!/usr/bin/env bash
# Downloads the Tailwind v4 standalone CLI (no Node required) and builds static/css/app.css.
# Usage: scripts/tailwind.sh [--watch]
set -euo pipefail

TAILWIND_VERSION="${TAILWIND_VERSION:-v4.3.3}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN_DIR="$ROOT/.bin"
BIN="$BIN_DIR/tailwindcss"

os="$(uname -s | tr '[:upper:]' '[:lower:]')"
arch="$(uname -m)"
case "$os-$arch" in
  darwin-arm64) asset="tailwindcss-macos-arm64" ;;
  darwin-x86_64) asset="tailwindcss-macos-x64" ;;
  linux-aarch64|linux-arm64) asset="tailwindcss-linux-arm64" ;;
  linux-x86_64) asset="tailwindcss-linux-x64" ;;
  *) echo "unsupported platform: $os-$arch" >&2; exit 1 ;;
esac

if [ ! -x "$BIN" ] || [ "$(cat "$BIN_DIR/.version" 2>/dev/null)" != "$TAILWIND_VERSION" ]; then
  mkdir -p "$BIN_DIR"
  curl -fsSL "https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/${asset}" -o "$BIN"
  chmod +x "$BIN"
  echo "$TAILWIND_VERSION" > "$BIN_DIR/.version"
fi

mkdir -p "$ROOT/static/css"
exec "$BIN" -i "$ROOT/static/src/app.css" -o "$ROOT/static/css/app.css" --minify "$@"
