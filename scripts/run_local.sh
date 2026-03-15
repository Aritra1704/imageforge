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

: "${PORT:=8090}"

PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Missing virtualenv interpreter at $PYTHON_BIN" >&2
  echo "Create it with: python3 -m venv .venv" >&2
  echo "Then install deps with: .venv/bin/python -m pip install -e \".[dev]\"" >&2
  exit 1
fi

exec "$PYTHON_BIN" -m uvicorn app.main:create_app --factory --host 0.0.0.0 --port "$PORT" --reload
