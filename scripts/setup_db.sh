#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

: "${DATABASE_URL:=postgresql://postgres:postgres@localhost:5432/postgres}"

psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "CREATE SCHEMA IF NOT EXISTS imageforge;"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$ROOT_DIR/db/schema.sql"
