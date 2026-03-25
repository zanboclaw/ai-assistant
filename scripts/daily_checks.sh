#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[daily] python compile check"
bash scripts/py_compile_check.sh

echo "[daily] web syntax check"
npm run check:web

echo "[daily] focused pytest smoke"
if [[ -n "${PYTEST_TARGETS:-}" ]]; then
  # shellcheck disable=SC2086
  pytest ${PYTEST_TARGETS} ${PYTEST_ARGS:-}
else
  pytest \
    tests/test_api_task_control_routes.py \
    tests/test_worker_validation.py \
    tests/test_worker_deliverable_prompt_sanitization.py \
    tests/test_long_term_memory.py \
    tests/test_version_metadata.py \
    -q ${PYTEST_ARGS:-}
fi
