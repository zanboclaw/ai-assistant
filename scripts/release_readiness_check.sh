#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

RUN_VALIDATION_SCRIPTS="${RUN_VALIDATION_SCRIPTS:-0}"
RUN_RELEASE_SERVICES="${RUN_RELEASE_SERVICES:-0}"
RUN_REGRESSION_CHECKS="${RUN_REGRESSION_CHECKS:-0}"
TEMP_ENV_CREATED=0

if [[ ! -f .env && -f .env.example ]]; then
  cp .env.example .env
  TEMP_ENV_CREATED=1
fi

cleanup() {
  if [[ "$TEMP_ENV_CREATED" == "1" ]]; then
    python3 - <<'PY'
from pathlib import Path
path = Path(".env")
if path.exists():
    path.unlink()
PY
  fi
}
trap cleanup EXIT

echo "[release] checking repository hygiene"
git status --short
git ls-files --error-unmatch .env >/dev/null 2>&1 && {
  echo "[release] .env is tracked, aborting"
  exit 1
} || true

echo "[release] running daily check entrypoint"
bash scripts/daily_checks.sh

if [[ "$RUN_REGRESSION_CHECKS" == "1" ]]; then
  echo "[release] running regression check entrypoint"
  bash scripts/regression_checks.sh
fi

if [[ -f package.json ]]; then
  echo "[release] package.json detected"
fi

echo "[release] validating docker compose files"
docker compose -f infra/compose/docker-compose.yml config -q
docker compose -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.validation.yml config -q

if [[ "$RUN_RELEASE_SERVICES" == "1" ]]; then
  echo "[release] starting validation stack"
  docker compose -f infra/compose/docker-compose.yml up -d --build
  if ! python3 scripts/run_migrations.py; then
    echo "[release] migrations failed"
    echo "[release] if the error mentions password authentication failed and you are reusing a local postgres volume,"
    echo "[release] run: bash scripts/repair_local_postgres_auth.sh"
    exit 1
  fi
  bash scripts/runtime_version_check.sh
fi

if [[ "$RUN_VALIDATION_SCRIPTS" == "1" ]]; then
  echo "[release] running validation scripts"
  bash scripts/healthcheck.sh
  bash scripts/acceptance_check.sh
  bash scripts/governance_check.sh
  bash scripts/session_memory_check.sh
  bash scripts/approval_retry_check.sh
  bash scripts/claim_lease_check.sh
  bash scripts/daily_review_check.sh
fi

echo "[release] readiness checks completed"
