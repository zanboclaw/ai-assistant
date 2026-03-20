#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-${ROOT_DIR}/logs}"
API_BASE="${API_BASE:-http://127.0.0.1:8000}"
mkdir -p "$LOG_DIR"
source "${ROOT_DIR}/scripts/http_fallback.sh"

TS="$(date +%F_%H%M%S)"
LOG_FILE="${LOG_DIR}/stage7_closure_check_${TS}.log"

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

run_check "Stage 7 Mainline Check" "cd '$ROOT_DIR' && bash scripts/stage7_mainline_check.sh"

section "Verify Stage 7 Readiness Metrics"
overview_resp="$(api_request GET "/monitor/overview")"
stage7_active="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.groundwork_active" | tr -d '"')"
stage7_operational="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.operational" | tr -d '"')"
stage7_completed="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.completed" | tr -d '"')"
stage7_groundwork_completed="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.groundwork_completed" | tr -d '"')"
stage7_groundwork_ratio="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.groundwork_ratio" | tr -d '"')"
stage7_shadow_completion_ratio="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.shadow_completion_ratio" | tr -d '"')"
stage7_workflow_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.workflow_improvement_change_request_count" | tr -d '"')"
stage7_shadow_completed_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.shadow_completed_change_request_count" | tr -d '"')"
stage7_candidate_overlay_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.candidate_overlay_validation_count" | tr -d '"')"
stage7_candidate_match_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.candidate_match_change_request_count" | tr -d '"')"
stage7_patch_ready_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.patch_artifact_ready_count" | tr -d '"')"
stage7_rollback_ready_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.rollback_ready_count" | tr -d '"')"
stage7_rollback_change_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.rollback_change_request_count" | tr -d '"')"
stage7_rollback_applied_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.rollback_applied_count" | tr -d '"')"
stage7_missing_gates="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.missing_groundwork_gates" | tr -d '\n')"

if [[ "$stage7_active" == "true" && "$stage7_operational" == "true" && "$stage7_groundwork_completed" == "true" && "$stage7_completed" == "false" ]]; then
  pass "Stage 7 closure 已正确表达 groundwork active/completed 与 overall 未完成"
else
  fail "Stage 7 closure readiness 状态异常: ${overview_resp}"
fi

if [[ "$stage7_groundwork_ratio" =~ ^(1|1\.0)$ && "$stage7_missing_gates" == "[]" ]]; then
  pass "Stage 7 groundwork ratio 达到 1.0 且无缺失 gate"
else
  fail "Stage 7 groundwork ratio 或 gate 记录异常: ${overview_resp}"
fi

if [[ "$stage7_shadow_completion_ratio" =~ ^(1|1\.0|0\.[0-9]+)$ && "$stage7_workflow_count" =~ ^[1-9][0-9]*$ && "$stage7_shadow_completed_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "Stage 7 workflow/shadow completion 聚合可读"
else
  fail "Stage 7 workflow/shadow completion 聚合异常: ${overview_resp}"
fi

if [[ "$stage7_candidate_overlay_count" =~ ^[1-9][0-9]*$ && "$stage7_candidate_match_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "Stage 7 candidate overlay 与 payload hash precision gate 已进入聚合"
else
  fail "Stage 7 candidate overlay / precision gate 聚合异常: ${overview_resp}"
fi

if [[ "$stage7_patch_ready_count" =~ ^[1-9][0-9]*$ && "$stage7_rollback_ready_count" =~ ^[1-9][0-9]*$ && "$stage7_rollback_change_count" =~ ^[1-9][0-9]*$ && "$stage7_rollback_applied_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "Stage 7 patch artifact 与 rollback 闭环已进入聚合"
else
  fail "Stage 7 patch artifact / rollback 聚合异常: ${overview_resp}"
fi

section "Verify Version Metadata"
version_state="$(python3 - <<'PY' "${ROOT_DIR}/version.json"
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as fh:
    data = json.load(fh)
print(json.dumps({
    "current_version": data.get("current_version", ""),
    "stage5": data.get("stages", {}).get("stage_5_multi_agent_layer", ""),
    "stage6": data.get("stages", {}).get("stage_6_evaluation_and_self_improvement", ""),
    "stage7": data.get("stages", {}).get("stage_7_safe_self_modification_and_rollback", ""),
}, ensure_ascii=False))
PY
)"
current_version="$(printf '%s' "$version_state" | extract_json_field "current_version" | tr -d '"')"
stage5_version_status="$(printf '%s' "$version_state" | extract_json_field "stage5" | tr -d '"')"
stage6_version_status="$(printf '%s' "$version_state" | extract_json_field "stage6" | tr -d '"')"
stage7_version_status="$(printf '%s' "$version_state" | extract_json_field "stage7" | tr -d '"')"
if [[ "$current_version" == "stage7-groundwork-candidate-overlay-gated-mainline" && "$stage5_version_status" == "completed" && "$stage6_version_status" == "completed" && "$stage7_version_status" == "planned" ]]; then
  pass "version.json 与当前 Stage 7 closure 口径一致"
else
  fail "version.json 未对齐当前 Stage 7 closure 口径: ${version_state}"
fi

section "Done"
log "日志文件: $LOG_FILE"
log "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT}"

if (( FAIL_COUNT > 0 )); then
  exit 1
fi
