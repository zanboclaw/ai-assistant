#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-${ROOT_DIR}/logs}"
API_BASE="${API_BASE:-http://127.0.0.1:8000}"
WEB_BASE="${WEB_BASE:-http://127.0.0.1:8080}"
mkdir -p "$LOG_DIR"
source "${ROOT_DIR}/scripts/http_fallback.sh"

TS="$(date +%F_%H%M%S)"
LOG_FILE="${LOG_DIR}/stage56_readiness_check_${TS}.log"

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

section "Run Stage 5/6 Mainline Check"
if bash "${ROOT_DIR}/scripts/stage56_mainline_check.sh" 2>&1 | tee -a "$LOG_FILE"; then
  pass "stage56_mainline_check 已通过"
else
  fail "stage56_mainline_check 未通过"
fi

section "Read Version Metadata"
stage5_version_status="$(python3 - <<'PY' "${ROOT_DIR}/version.json"
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as fh:
    data = json.load(fh)
print(data.get("stages", {}).get("stage_5_multi_agent_layer", ""))
PY
)"
stage6_version_status="$(python3 - <<'PY' "${ROOT_DIR}/version.json"
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as fh:
    data = json.load(fh)
print(data.get("stages", {}).get("stage_6_evaluation_and_self_improvement", ""))
PY
)"
current_version="$(python3 - <<'PY' "${ROOT_DIR}/version.json"
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as fh:
    data = json.load(fh)
print(data.get("current_version", ""))
PY
)"

if [[ "$stage5_version_status" == "completed" && "$stage6_version_status" == "completed" && ( "$current_version" == "stage6-completed-shadow-validation-mainline" || "$current_version" == "stage7-groundwork-candidate-overlay-gated-mainline" ) ]]; then
  pass "version.json 与当前 Stage 5/6 completed 状态一致，且允许仓库继续前进到 Stage 7 groundwork"
else
  fail "version.json 未对齐当前 Stage 5/6 状态: current_version=${current_version} stage5=${stage5_version_status} stage6=${stage6_version_status}"
fi

section "Read Monitor Overview"
overview_resp="$(api_request GET "/monitor/overview")"
stage5_operational="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage5.operational" | tr -d '"')"
stage5_completed="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage5.completed" | tr -d '"')"
stage5_completion_ratio="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage5.completion_ratio" | tr -d '"')"
stage5_mainline_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage5.mainline_task_count" | tr -d '"')"
stage5_terminal_ready_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage5.terminal_ready_count" | tr -d '"')"
stage5_runtime_fanout_events="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage5.runtime_fanout_event_count" | tr -d '"')"
stage5_runtime_fanin_events="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage5.runtime_fanin_event_count" | tr -d '"')"
stage5_non_readonly_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage5.non_readonly_specialist_task_count" | tr -d '"')"
stage5_missing_gates="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage5.missing_completion_gates")"
stage6_operational="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage6.operational" | tr -d '"')"
stage6_completed="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage6.completed" | tr -d '"')"
stage6_completion_ratio="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage6.completion_ratio" | tr -d '"')"
stage6_mainline_eval_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage6.mainline_evaluator_run_count" | tr -d '"')"
stage6_failure_taxonomy_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage6.failure_taxonomy_count" | tr -d '"')"
stage6_bridge_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage6.mainline_bridged_change_request_count" | tr -d '"')"
stage6_shadow_validation_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage6.shadow_validation_count" | tr -d '"')"
stage6_missing_gates="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage6.missing_completion_gates")"

if [[ "$stage5_operational" == "true" && "$stage5_mainline_count" =~ ^[1-9][0-9]*$ && "$stage5_terminal_ready_count" =~ ^[1-9][0-9]*$ && "$stage5_runtime_fanout_events" =~ ^[1-9][0-9]*$ && "$stage5_runtime_fanin_events" =~ ^[1-9][0-9]*$ ]]; then
  pass "Stage 5 readiness 已证明主链 fan-out/fan-in + terminal postrun 可运行"
else
  fail "Stage 5 readiness 未达到主链 operational 基线: ${overview_resp}"
fi

if [[ "$stage5_completed" == "true" || "$stage5_completed" == "True" ]]; then
  pass "Stage 5 readiness 已升级为 completed"
else
  fail "Stage 5 readiness 未显示 completed: ${overview_resp}"
fi

if [[ "$stage5_missing_gates" == "[]" ]]; then
  pass "Stage 5 completion gates 已全部满足"
else
  fail "Stage 5 readiness 仍存在未满足 completion gate: ${stage5_missing_gates}"
fi

if [[ "$stage5_non_readonly_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "Stage 5 mainline 已出现 non-readonly specialist"
else
  fail "Stage 5 仍未出现 non-readonly specialist: count=${stage5_non_readonly_count}"
fi

if [[ "$stage6_operational" == "true" && "$stage6_mainline_eval_count" =~ ^[1-9][0-9]*$ && "$stage6_failure_taxonomy_count" =~ ^[1-9][0-9]*$ && "$stage6_bridge_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "Stage 6 readiness 已证明 evaluator/proposal/bridge 主链可运行"
else
  fail "Stage 6 readiness 未达到主链 operational 基线: ${overview_resp}"
fi

if [[ "$stage6_completed" == "true" || "$stage6_completed" == "True" ]]; then
  pass "Stage 6 readiness 已升级为 completed"
else
  fail "Stage 6 readiness 未显示 completed: ${overview_resp}"
fi

if [[ "$stage6_missing_gates" == "[]" ]]; then
  pass "Stage 6 completion gates 已全部满足"
else
  fail "Stage 6 readiness 仍存在未满足 completion gate: ${stage6_missing_gates}"
fi

if [[ "$stage6_shadow_validation_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "Stage 6 mainline 已出现 shadow validation count=${stage6_shadow_validation_count}"
else
  fail "Stage 6 尚未聚合 shadow validation: count=${stage6_shadow_validation_count}"
fi

if [[ "$stage5_completion_ratio" =~ ^(1|1\.0)$ && "$stage6_completion_ratio" =~ ^(1|1\.0)$ ]]; then
  pass "Stage 5/6 completion_ratio 已达到 1.0 stage5=${stage5_completion_ratio} stage6=${stage6_completion_ratio}"
else
  fail "Stage 5/6 completion_ratio 不可读: stage5=${stage5_completion_ratio} stage6=${stage6_completion_ratio}"
fi

section "Done"
log "日志文件: $LOG_FILE"
log "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT} WARN=${WARN_COUNT}"

if (( FAIL_COUNT > 0 )); then
  exit 1
fi
