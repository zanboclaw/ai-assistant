#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-${ROOT_DIR}/logs}"
mkdir -p "$LOG_DIR"

TS="$(date +%F_%H%M%S)"
LOG_FILE="${LOG_DIR}/stage_closure_check_${TS}.log"

PASS_COUNT=0
FAIL_COUNT=0

log() {
  echo "[$(date '+%F %T')] $*" | tee -a "$LOG_FILE"
}

section() {
  echo | tee -a "$LOG_FILE"
  echo "========== $* ==========" | tee -a "$LOG_FILE"
}

run_check() {
  local name="$1"
  local cmd="$2"

  section "$name"
  if bash -lc "$cmd" 2>&1 | tee -a "$LOG_FILE"; then
    PASS_COUNT=$((PASS_COUNT + 1))
    log "PASS: $name"
  else
    FAIL_COUNT=$((FAIL_COUNT + 1))
    log "FAIL: $name"
  fi
}

run_check "Stage 3 Session Closure" "cd '$ROOT_DIR' && bash scripts/session_memory_check.sh"
run_check "Stage 3 Daily Review Closure" "cd '$ROOT_DIR' && bash scripts/daily_review_check.sh"
run_check "Stage 4 Governance Closure" "cd '$ROOT_DIR' && bash scripts/governance_check.sh"
run_check "Web Console Smoke" "cd '$ROOT_DIR' && bash scripts/web_console_check.sh"

section "Done"
log "日志文件: $LOG_FILE"
log "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT}"

if (( FAIL_COUNT > 0 )); then
  exit 1
fi
