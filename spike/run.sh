#!/usr/bin/env bash
# A one-command test run of the Phase 0 spike.
#
#   spike/run.sh              full E2E run (needs LLM_ROUTER_API_KEY)
#   spike/run.sh --dry-run    prepare the isolated workspace and CODEX_HOME only
#   spike/run.sh --model M    pick a model alias
#   spike/run.sh --timeout N  wall-clock seconds for the agent run
#
# Arguments are passed straight to spike/run_spike.py. The checks below exist
# because the two ways this fails (no key, no codex) otherwise surface as a
# confusing traceback or a silent no-run.

set -euo pipefail

cd "$(dirname "$0")/.."

DRY_RUN=false
for arg in "$@"; do
    [ "$arg" = "--dry-run" ] && DRY_RUN=true
done

if [ ! -e .venv/bin/python ]; then
    echo "note: no .venv here; using python3 (create one with: uv venv --python 3.12 .venv)" >&2
    PYTHON=python3
else
    PYTHON=.venv/bin/python
fi

if ! command -v codex >/dev/null 2>&1; then
    echo "error: the 'codex' executable is not on PATH" >&2
    exit 1
fi

if [ "$DRY_RUN" = false ] && [ -z "${LLM_ROUTER_API_KEY:-}" ]; then
    echo "error: LLM_ROUTER_API_KEY is not set (use --dry-run to prepare without it)" >&2
    exit 1
fi

echo "python:  $PYTHON"
echo "codex:   $(command -v codex)"
echo "artifacts: data/artifacts/spike/<run_id>/"

exec "$PYTHON" spike/run_spike.py "$@"
