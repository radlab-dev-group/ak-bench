#!/usr/bin/env bash
set -euo pipefail

# Determine script and project directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

# Default connection parameters
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

echo "=================================================="
echo " Starting AK-Bench Interactive Dashboard UI"
echo " URL: http://${HOST}:${PORT}"
echo "=================================================="

# Prefer `uv run` to guarantee resolved dependencies; fallback gracefully to python/venv
if command -v uv >/dev/null 2>&1; then
    exec uv run akbench ui --host "${HOST}" --port "${PORT}" "$@"
elif [ -n "${VIRTUAL_ENV:-}" ] && command -v python >/dev/null 2>&1; then
    exec python -m bench_ui --host "${HOST}" --port "${PORT}" "$@"
elif [ -x "${SCRIPT_DIR}/.venv/bin/python" ]; then
    exec "${SCRIPT_DIR}/.venv/bin/python" -m bench_ui --host "${HOST}" --port "${PORT}" "$@"
else
    exec python3 -m bench_ui --host "${HOST}" --port "${PORT}" "$@"
fi
