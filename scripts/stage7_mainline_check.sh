#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-${ROOT_DIR}/logs}"
mkdir -p "$LOG_DIR"

TS="$(date +%F_%H%M%S)"
LOG_FILE="${LOG_DIR}/stage7_mainline_check_${TS}.log"

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

run_check "Web Console Stage 7 Visibility" "cd '$ROOT_DIR' && bash scripts/web_console_check.sh"
run_check "Workflow Proposal Precision Gate" "cd '$ROOT_DIR' && bash scripts/workflow_proposal_bridge_check.sh"
run_check "Stage 7 Shadow Status Sync" "cd '$ROOT_DIR' && bash scripts/stage7_shadow_validation_status_check.sh"
run_check "Stage 7 Summarize Route Override" "cd '$ROOT_DIR' && bash scripts/stage7_model_route_override_check.sh"
run_check "Stage 7 Web Search Route Override" "cd '$ROOT_DIR' && bash scripts/stage7_web_search_route_override_check.sh"
run_check "Stage 7 Sandbox File Source Copy" "cd '$ROOT_DIR' && bash scripts/stage7_sandbox_file_change_check.sh"
run_check "Stage 7 Sandbox Bridge Source Copy" "cd '$ROOT_DIR' && bash scripts/stage7_sandbox_file_bridge_check.sh"
run_check "Stage 7 Rollback Closure" "cd '$ROOT_DIR' && bash scripts/change_request_rollback_check.sh"

section "Done"
log "日志文件: $LOG_FILE"
log "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT}"

if (( FAIL_COUNT > 0 )); then
  exit 1
fi
