#!/usr/bin/env bash
set -euo pipefail

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  echo ">>> applying migrations"
  python manage.py migrate --noinput
fi

exec "$@"
