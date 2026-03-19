#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-${ROOT_DIR}/logs}"
API_BASE="${API_BASE:-http://127.0.0.1:8000}"
mkdir -p "$LOG_DIR"
source "${ROOT_DIR}/scripts/http_fallback.sh"

TS="$(date +%F_%H%M%S)"
LOG_FILE="${LOG_DIR}/stage6_shadow_validation_check_${TS}.log"

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

section "Create Baseline Task"
task_resp="$(python3 - <<'PY' | api_request_stdin POST "/tasks" "local_admin"
import json
print(json.dumps({
    "user_input": "读取 JSON 文件 /workspace/sample.json 并整理要点"
}, ensure_ascii=False))
PY
)"
task_id="$(printf '%s' "$task_resp" | extract_json_field "id" | tr -d '"')"
if [[ "$task_id" =~ ^[0-9]+$ ]]; then
  pass "成功创建 shadow validation baseline task #$task_id"
else
  fail "创建 baseline task 失败: $task_resp"
fi

section "Wait Baseline Terminal Status"
task_status=""
task_state=""
for _ in $(seq 1 40); do
  task_state="$(api_request GET "/tasks/${task_id}")"
  task_status="$(printf '%s' "$task_state" | extract_json_field "status" | tr -d '"')"
  if [[ "$task_status" == "completed" || "$task_status" == "failed" ]]; then
    break
  fi
  sleep 1
done

if [[ "$task_status" == "completed" || "$task_status" == "failed" ]]; then
  pass "baseline task 进入终态 status=${task_status}"
else
  fail "baseline task 未进入终态: ${task_state}"
fi

section "Resolve Workflow Proposal"
proposal_resp="$(api_request GET "/tasks/${task_id}/workflow-proposals/latest")"
proposal_id="$(printf '%s' "$proposal_resp" | extract_json_field "id" | tr -d '"')"
proposal_source="$(printf '%s' "$proposal_resp" | extract_json_field "source" | tr -d '"')"
baseline_score="$(printf '%s' "$proposal_resp" | extract_json_field "score" | tr -d '"')"
if [[ "$proposal_id" =~ ^[0-9]+$ && "$proposal_source" == "task_runtime_postrun_v1" && "$baseline_score" =~ ^[0-9]+$ ]]; then
  pass "baseline task 已产出主链 workflow proposal"
else
  fail "baseline task workflow proposal 异常: $proposal_resp"
fi

section "Run Shadow Validation"
shadow_resp="$(python3 - <<'PY' | api_request_stdin POST "/workflow-proposals/${proposal_id}/shadow-validate" "local_admin"
import json
print(json.dumps({
    "note": "stage6 shadow validation smoke",
    "await_completion": True,
    "timeout_seconds": 60,
    "poll_interval_seconds": 1.0
}, ensure_ascii=False))
PY
)"
shadow_completed="$(printf '%s' "$shadow_resp" | extract_json_field "completed" | tr -d '"')"
shadow_task_id="$(printf '%s' "$shadow_resp" | extract_json_field "shadow_task.id" | tr -d '"')"
shadow_task_status="$(printf '%s' "$shadow_resp" | extract_json_field "shadow_task.status" | tr -d '"')"
shadow_eval_id="$(printf '%s' "$shadow_resp" | extract_json_field "shadow_evaluator.id" | tr -d '"')"
validation_result="$(printf '%s' "$shadow_resp" | extract_json_field "validation.validation_result" | tr -d '"')"
shadow_score="$(printf '%s' "$shadow_resp" | extract_json_field "validation.shadow_score" | tr -d '"')"
score_delta="$(printf '%s' "$shadow_resp" | extract_json_field "validation.score_delta" | tr -d '"')"

if [[ "$shadow_completed" == "true" && "$shadow_task_id" =~ ^[0-9]+$ && "$shadow_eval_id" =~ ^[0-9]+$ ]]; then
  pass "shadow validation 已完成 shadow_task_id=${shadow_task_id}"
else
  fail "shadow validation 未完成: $shadow_resp"
fi

if [[ "$shadow_task_status" == "completed" || "$shadow_task_status" == "failed" ]]; then
  pass "shadow task 已进入终态 status=${shadow_task_status}"
else
  fail "shadow task 未进入终态: $shadow_resp"
fi

if [[ "$validation_result" == "matched" || "$validation_result" == "improved" || "$validation_result" == "regressed" || "$validation_result" == "changed" ]]; then
  pass "shadow validation 返回可读比较结果 result=${validation_result} shadow_score=${shadow_score} score_delta=${score_delta}"
else
  fail "shadow validation 比较结果异常: $shadow_resp"
fi

section "Verify Shadow Task Evaluator"
shadow_eval_resp="$(api_request GET "/tasks/${shadow_task_id}/evaluator-runs/latest")"
shadow_eval_source="$(printf '%s' "$shadow_eval_resp" | extract_json_field "source" | tr -d '"')"
if [[ "$shadow_eval_source" == "task_runtime_postrun_v1" ]]; then
  pass "shadow task 通过主链 postrun 产出 evaluator"
else
  fail "shadow task evaluator source 异常: $shadow_eval_resp"
fi

section "Verify Audit Trail"
validation_audit_resp="$(api_request GET "/audit-logs?event_type=workflow_proposal.shadow_validation&limit=10")"
validation_audit_match="$(printf '%s' "$validation_audit_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(any(int((item.get("details") or {}).get("proposal_id") or 0)==int(sys.argv[1]) for item in data))' "$proposal_id")"
validated_audit_resp="$(api_request GET "/audit-logs?event_type=workflow_proposal.shadow_validated&limit=10")"
validated_audit_match="$(printf '%s' "$validated_audit_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(any(int((item.get("details") or {}).get("proposal_id") or 0)==int(sys.argv[1]) for item in data))' "$proposal_id")"

if [[ "$validation_audit_match" == "True" ]]; then
  pass "audit log 记录了 workflow_proposal.shadow_validation"
else
  fail "audit log 未记录 workflow_proposal.shadow_validation: $validation_audit_resp"
fi

if [[ "$validated_audit_match" == "True" ]]; then
  pass "audit log 记录了 workflow_proposal.shadow_validated"
else
  fail "audit log 未记录 workflow_proposal.shadow_validated: $validated_audit_resp"
fi

section "Verify Monitor Overview"
monitor_resp="$(api_request GET "/monitor/overview")"
shadow_validation_count="$(printf '%s' "$monitor_resp" | extract_json_field "readiness_metrics.stage6.shadow_validation_count" | tr -d '"')"
stage6_completed="$(printf '%s' "$monitor_resp" | extract_json_field "readiness_metrics.stage6.completed" | tr -d '"')"
stage6_missing_gates="$(printf '%s' "$monitor_resp" | extract_json_field "readiness_metrics.stage6.missing_completion_gates")"

if [[ "$shadow_validation_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "monitor/overview 已聚合 Stage 6 shadow validation 计数 count=${shadow_validation_count}"
else
  fail "monitor/overview 未聚合 Stage 6 shadow validation: $monitor_resp"
fi

if [[ "$stage6_completed" == "true" && "$stage6_missing_gates" == "[]" ]]; then
  pass "Stage 6 readiness 已因 shadow validation 达到 completed"
else
  fail "Stage 6 readiness 未升级为 completed: $monitor_resp"
fi

section "Done"
log "日志文件: $LOG_FILE"
log "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT} WARN=${WARN_COUNT}"

if (( FAIL_COUNT > 0 )); then
  exit 1
fi
