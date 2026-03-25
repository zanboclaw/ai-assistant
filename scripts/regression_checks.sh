#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[regression] running layered daily checks"
bash scripts/daily_checks.sh

echo "[regression] running mainline pytest regression set"
if [[ -z "${PYTEST_TARGETS:-}" ]]; then
  pytest \
    tests/test_api_routes_integration.py \
    tests/test_api_task_control_routes.py \
    tests/test_api_governance_routes.py \
    tests/test_api_monitor_routes.py \
    tests/test_worker_task_processing_runtime.py \
    tests/test_worker_search_query_sanitization.py \
    tests/test_worker_deliverable_prompt_sanitization.py \
    tests/test_worker_validation.py \
    tests/test_long_term_memory.py \
    tests/test_version_metadata.py \
    tests/test_access_control.py \
    -q ${PYTEST_ARGS:-}
fi

if [[ "${RUN_E2E:-0}" == "1" ]]; then
  echo "[regression] running dashboard e2e"
  npx playwright test tests/e2e/dashboard.spec.js
fi
