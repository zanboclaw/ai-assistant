#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-${ROOT_DIR}/logs}"
API_BASE="${API_BASE:-http://127.0.0.1:8000}"
WEB_BASE="${WEB_BASE:-http://127.0.0.1:8080}"
mkdir -p "$LOG_DIR"
source "${ROOT_DIR}/scripts/http_fallback.sh"

TS="$(date +%F_%H%M%S)"
LOG_FILE="${LOG_DIR}/stage7_readiness_check_${TS}.log"

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0

log() {
  echo "[$(date '+%F %T')] $*" | tee -a "$LOG_FILE"
}

pass() {
  PASS_COUNT=$((PASS_COUNT + 1))
  log "PASS: $*"
}

fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  log "FAIL: $*"
}

warn() {
  WARN_COUNT=$((WARN_COUNT + 1))
  log "WARN: $*"
}

section() {
  echo | tee -a "$LOG_FILE"
  echo "========== $* ==========" | tee -a "$LOG_FILE"
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

section "Wait Services Ready"
services_ready="false"
for _ in $(seq 1 30); do
  if check_api_ready && check_web_ready; then
    services_ready="true"
    break
  fi
  sleep 1
done

if [[ "$services_ready" == "true" ]]; then
  pass "API/Web 已就绪"
else
  fail "API/Web 未在预期时间内就绪 api=${API_BASE} web=${WEB_BASE}"
fi

section "Run Stage 7 Mainline Check"
if bash "${ROOT_DIR}/scripts/stage7_mainline_check.sh" 2>&1 | tee -a "$LOG_FILE"; then
  pass "stage7_mainline_check 已通过"
else
  fail "stage7_mainline_check 未通过"
fi

section "Read Version Metadata"
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
if [[ "$current_version" == "stage7-safe-self-modification-mainline" && "$stage5_version_status" == "completed" && "$stage6_version_status" == "completed" && "$stage7_version_status" == "completed" ]]; then
  pass "version.json 与当前 Stage 7 completed 口径一致"
else
  fail "version.json 未对齐当前 Stage 7 状态: ${version_state}"
fi

section "Read Monitor Overview"
overview_resp="$(api_request GET "/monitor/overview")"
stage5_completed="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage5.completed" | tr -d '"')"
stage6_completed="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage6.completed" | tr -d '"')"
stage7_active="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.groundwork_active" | tr -d '"')"
stage7_operational="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.operational" | tr -d '"')"
stage7_overall_completed="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.overall_completed" | tr -d '"')"
stage7_completed="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.completed" | tr -d '"')"
stage7_groundwork_completed="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.groundwork_completed" | tr -d '"')"
stage7_groundwork_ratio="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.groundwork_ratio" | tr -d '"')"
stage7_completion_ratio="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.completion_ratio" | tr -d '"')"
stage7_workflow_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.workflow_improvement_change_request_count" | tr -d '"')"
stage7_shadow_completed_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.shadow_completed_change_request_count" | tr -d '"')"
stage7_candidate_overlay_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.candidate_overlay_validation_count" | tr -d '"')"
stage7_candidate_match_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.candidate_match_change_request_count" | tr -d '"')"
stage7_patch_ready_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.patch_artifact_ready_count" | tr -d '"')"
stage7_rollback_ready_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.rollback_ready_count" | tr -d '"')"
stage7_rollback_change_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.rollback_change_request_count" | tr -d '"')"
stage7_rollback_applied_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.rollback_applied_count" | tr -d '"')"
stage7_sandbox_source_patch_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.sandbox_source_patch_applied_count" | tr -d '"')"
stage7_sandbox_acceptance_passed_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.sandbox_acceptance_passed_count" | tr -d '"')"
stage7_sandbox_acceptance_failed_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.sandbox_acceptance_failed_count" | tr -d '"')"
stage7_sandbox_auto_rollback_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.sandbox_auto_rollback_applied_count" | tr -d '"')"
stage7_missing_gates="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.missing_groundwork_gates" | tr -d '\n')"
stage7_missing_completion_gates="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.missing_completion_gates" | tr -d '\n')"

if [[ "$stage5_completed" == "true" && "$stage6_completed" == "true" ]]; then
  pass "Stage 5/6 completed 状态仍保持不回退"
else
  fail "Stage 5/6 completed 状态异常: ${overview_resp}"
fi

if [[ "$stage7_active" == "true" && "$stage7_operational" == "true" && "$stage7_groundwork_completed" == "true" && "$stage7_overall_completed" == "true" && "$stage7_completed" == "true" ]]; then
  pass "Stage 7 readiness 已升级为 overall completed=true"
else
  fail "Stage 7 readiness 状态位异常: ${overview_resp}"
fi

if [[ "$stage7_groundwork_ratio" =~ ^(1|1\.0)$ && "$stage7_missing_gates" == "[]" ]]; then
  pass "Stage 7 groundwork gates 已全部满足"
else
  fail "Stage 7 groundwork gates 记录异常: ${overview_resp}"
fi

if [[ "$stage7_completion_ratio" =~ ^(1|1\.0)$ && "$stage7_missing_completion_gates" == "[]" ]]; then
  pass "Stage 7 overall completion gates 已全部满足"
else
  fail "Stage 7 overall completion gates 记录异常: ${overview_resp}"
fi

if [[ "$stage7_workflow_count" =~ ^[1-9][0-9]*$ && "$stage7_shadow_completed_count" =~ ^[1-9][0-9]*$ && "$stage7_candidate_overlay_count" =~ ^[1-9][0-9]*$ && "$stage7_candidate_match_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "Stage 7 shadow validation / precision gate 计数可读"
else
  fail "Stage 7 shadow validation / precision gate 计数异常: ${overview_resp}"
fi

if [[ "$stage7_patch_ready_count" =~ ^[1-9][0-9]*$ && "$stage7_rollback_ready_count" =~ ^[1-9][0-9]*$ && "$stage7_rollback_change_count" =~ ^[1-9][0-9]*$ && "$stage7_rollback_applied_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "Stage 7 patch artifact / rollback 计数可读"
else
  fail "Stage 7 patch artifact / rollback 计数异常: ${overview_resp}"
fi

if [[ "$stage7_sandbox_source_patch_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "Stage 7 source-patch 实验计数可读"
else
  fail "Stage 7 source-patch 实验计数异常: ${overview_resp}"
fi

if [[ "$stage7_sandbox_acceptance_passed_count" =~ ^[1-9][0-9]*$ && "$stage7_sandbox_acceptance_failed_count" =~ ^[1-9][0-9]*$ && "$stage7_sandbox_auto_rollback_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "Stage 7 acceptance / auto rollback 实验计数可读"
else
  fail "Stage 7 acceptance / auto rollback 实验计数异常: ${overview_resp}"
fi

section "Done"
log "日志文件: $LOG_FILE"
log "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT} WARN=${WARN_COUNT}"

if (( FAIL_COUNT > 0 )); then
  exit 1
fi
