#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-${ROOT_DIR}/logs}"
API_BASE="${API_BASE:-http://127.0.0.1:8000}"
mkdir -p "$LOG_DIR"
source "${ROOT_DIR}/scripts/http_fallback.sh"

TS="$(date +%F_%H%M%S)"
LOG_FILE="${LOG_DIR}/stage56_closure_check_${TS}.log"

PASS_COUNT=0
FAIL_COUNT=0

log() {
  echo "[$(date '+%F %T')] $*" | tee -a "$LOG_FILE"
}

section() {
  echo | tee -a "$LOG_FILE"
  echo "========== $* ==========" | tee -a "$LOG_FILE"
}

pass() {
  PASS_COUNT=$((PASS_COUNT + 1))
  log "PASS: $*"
}

fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  log "FAIL: $*"
}

run_check() {
  local name="$1"
  local cmd="$2"

  section "$name"
  if bash -lc "$cmd" 2>&1 | tee -a "$LOG_FILE"; then
    pass "$name"
  else
    fail "$name"
  fi
}

extract_json_field() {
  local field="$1"
  python3 -c 'import json, sys
data = json.load(sys.stdin)
value = data
for part in sys.argv[1].split("."):
    if isinstance(value, dict):
        value = value.get(part)
    else:
        value = None
        break
print(json.dumps(value, ensure_ascii=False))' "$field"
}

run_check "Stage 5/6 Mainline Check" "cd '$ROOT_DIR' && bash scripts/stage56_mainline_check.sh"

section "Verify Stage 5/6 Readiness Metrics"
overview_resp="$(api_request GET "/monitor/overview")"

stage5_runtime_ratio="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage5.runtime_fanout_ratio" | tr -d '"')"
stage5_role_ratio="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage5.role_skeleton_ratio" | tr -d '"')"
stage5_terminal_ratio="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage5.terminal_readiness_ratio" | tr -d '"')"
stage5_operational="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage5.operational" | tr -d '"')"
stage5_completed="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage5.completed" | tr -d '"')"
stage5_completion_ratio="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage5.completion_ratio" | tr -d '"')"
stage5_missing_gates="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage5.missing_completion_gates" | tr -d '\n')"
stage5_mainline_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage5.mainline_task_count" | tr -d '"')"
stage5_terminal_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage5.terminal_mainline_task_count" | tr -d '"')"
stage5_fanout_events="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage5.runtime_fanout_event_count" | tr -d '"')"
stage5_fanin_events="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage5.runtime_fanin_event_count" | tr -d '"')"
stage6_proposal_ratio="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage6.workflow_proposal_coverage_ratio" | tr -d '"')"
stage6_auto_mapped_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage6.auto_mapped_proposal_count" | tr -d '"')"
stage6_bridged_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage6.mainline_bridged_change_request_count" | tr -d '"')"
stage6_bridge_ratio="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage6.bridge_activation_ratio" | tr -d '"')"
stage6_shadow_validation_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage6.shadow_validation_count" | tr -d '"')"
stage6_operational="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage6.operational" | tr -d '"')"
stage6_completed="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage6.completed" | tr -d '"')"
stage6_completion_ratio="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage6.completion_ratio" | tr -d '"')"
stage6_missing_gates="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage6.missing_completion_gates" | tr -d '\n')"

if [[ "$stage5_role_ratio" == "1.0" && "$stage5_runtime_ratio" =~ ^(0\.9[0-9]*|1|1\.0)$ && "$stage5_terminal_ratio" =~ ^(0\.9[0-9]*|1|1\.0)$ ]]; then
  pass "Stage 5 骨架覆盖完整，runtime/terminal 收口比例达到当前 closure 基线"
else
  fail "Stage 5 closure 基线异常 role=${stage5_role_ratio} runtime=${stage5_runtime_ratio} terminal=${stage5_terminal_ratio} overview=${overview_resp}"
fi

if [[ "$stage5_operational" == "True" || "$stage5_operational" == "true" ]]; then
  pass "Stage 5 operational 指标为 true"
else
  fail "Stage 5 operational 指标异常: $overview_resp"
fi

if [[ "$stage5_mainline_count" =~ ^[1-9][0-9]*$ && "$stage5_terminal_count" =~ ^[1-9][0-9]*$ && "$stage5_fanout_events" =~ ^[1-9][0-9]*$ && "$stage5_fanin_events" =~ ^[1-9][0-9]*$ ]]; then
  pass "Stage 5 mainline/terminal 计数和 runtime 审计事件可读"
else
  fail "Stage 5 mainline/terminal 计数或 runtime 审计事件异常: $overview_resp"
fi

if [[ "$stage5_completion_ratio" =~ ^(1|1\.0)$ && ( "$stage5_completed" == "true" || "$stage5_completed" == "True" ) && "$stage5_missing_gates" == "[]" ]]; then
  pass "Stage 5 completion gate 已全部满足"
else
  fail "Stage 5 completion gate 记录异常: $overview_resp"
fi

if [[ "$stage6_proposal_ratio" == "1.0" && "$stage6_bridge_ratio" =~ ^(1|1\.0|0\.[0-9]+)$ ]]; then
  pass "Stage 6 proposal 覆盖率可读且达到 1.0"
else
  fail "Stage 6 proposal 覆盖率异常: $overview_resp"
fi

if [[ "$stage6_auto_mapped_count" =~ ^[1-9][0-9]*$ && "$stage6_bridged_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "Stage 6 auto-mapped proposal 与 bridged change request 计数可读"
else
  fail "Stage 6 auto-mapped proposal 或 bridged change request 计数异常: $overview_resp"
fi

if [[ "$stage6_operational" == "True" || "$stage6_operational" == "true" ]]; then
  pass "Stage 6 operational 指标为 true"
else
  fail "Stage 6 operational 指标异常: $overview_resp"
fi

if [[ "$stage6_completion_ratio" =~ ^(1|1\.0)$ && ( "$stage6_completed" == "true" || "$stage6_completed" == "True" ) && "$stage6_missing_gates" == "[]" && "$stage6_shadow_validation_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "Stage 6 completion gate 已全部满足，shadow validation 已进入主链闭环"
else
  fail "Stage 6 completion gate 记录异常: $overview_resp"
fi

section "Done"
log "日志文件: $LOG_FILE"
log "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT}"

if (( FAIL_COUNT > 0 )); then
  exit 1
fi
