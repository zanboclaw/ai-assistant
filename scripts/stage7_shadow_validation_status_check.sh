#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-${ROOT_DIR}/logs}"
API_BASE="${API_BASE:-http://127.0.0.1:8000}"
mkdir -p "$LOG_DIR"
source "${ROOT_DIR}/scripts/http_fallback.sh"

TS="$(date +%F_%H%M%S)"
LOG_FILE="${LOG_DIR}/stage7_shadow_validation_status_check_${TS}.log"

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

section "Init DB"
api_request POST "/init-db" "" "local_admin" >/dev/null
pass "数据库初始化成功"

section "Create Mainline Proposal Task"
task_resp="$(python3 - <<'PY' | api_request_stdin POST "/tasks" "local_admin"
import json
print(json.dumps({
    "user_input": "读取 JSON 文件 /workspace/sample.json 并整理要点"
}, ensure_ascii=False))
PY
)"
task_id="$(printf '%s' "$task_resp" | extract_json_field "id" | tr -d '"')"
if [[ "$task_id" =~ ^[0-9]+$ ]]; then
  pass "成功创建 shadow status baseline task #$task_id"
else
  fail "创建 shadow status baseline task 失败: $task_resp"
fi

section "Wait Task Terminal Status"
task_status=""
task_state=""
approval_done="false"
for _ in $(seq 1 40); do
  task_state="$(api_request GET "/tasks/${task_id}")"
  task_status="$(printf '%s' "$task_state" | extract_json_field "status" | tr -d '"')"
  if [[ "$task_status" == "waiting_approval" && "$approval_done" != "true" ]]; then
    approvals_resp="$(api_request GET "/tasks/${task_id}/approvals")"
    approval_id="$(printf '%s' "$approvals_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); pending=next((item for item in data if item.get("status")=="pending"), {}); print(pending.get("id") or "")')"
    if [[ "$approval_id" =~ ^[0-9]+$ ]]; then
      approve_resp="$(api_request POST "/approvals/${approval_id}/approve" '{"note":"stage7 shadow status smoke approve"}' "local_admin")"
      if echo "$approve_resp" | grep -q '"approval approved"'; then
        pass "已批准 baseline task 审批 approval_id=${approval_id}"
        approval_done="true"
      else
        fail "baseline task 审批批准异常: ${approve_resp}"
      fi
    fi
  fi
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
if [[ "$proposal_id" =~ ^[0-9]+$ && "$proposal_source" == "task_runtime_postrun_v1" ]]; then
  pass "baseline task 已产出主链 workflow proposal #${proposal_id}"
else
  fail "workflow proposal 解析异常: $proposal_resp"
fi

section "Verify Initial Shadow Status"
proposal_shadow_initial="$(api_request GET "/workflow-proposals/${proposal_id}/shadow-validation?history_limit=4" "" "local_admin")"
proposal_initial_status="$(printf '%s' "$proposal_shadow_initial" | extract_json_field "status" | tr -d '"')"
proposal_initial_history_count="$(printf '%s' "$proposal_shadow_initial" | extract_json_field "history_count" | tr -d '"')"
proposal_initial_validation_count="$(printf '%s' "$proposal_shadow_initial" | extract_json_field "validation_count" | tr -d '"')"
if [[ "$proposal_initial_status" == "not_started" && "$proposal_initial_history_count" == "0" && "$proposal_initial_validation_count" == "0" ]]; then
  pass "proposal shadow status 初始为 not_started"
else
  fail "proposal shadow status 初始状态异常: $proposal_shadow_initial"
fi

section "Create Workflow Improvement Change Request"
change_resp="$(python3 - <<'PY' | api_request_stdin POST "/workflow-proposals/${proposal_id}/change-request-draft" "local_admin"
import json
print(json.dumps({
    "target_type": "model_route",
    "target_key": "planner",
    "proposed_payload": {
        "provider": "deepseek_default",
        "model_name": "deepseek-chat",
        "temperature": 0.25,
        "max_tokens": 1900,
        "enabled": True,
        "description": "stage7 shadow status smoke route"
    },
    "rationale": "stage7 shadow status smoke create-change"
}, ensure_ascii=False))
PY
)"
change_request_id="$(printf '%s' "$change_resp" | extract_json_field "change_request.id" | tr -d '"')"
change_request_status="$(printf '%s' "$change_resp" | extract_json_field "change_request.status" | tr -d '"')"
if [[ "$change_request_id" =~ ^[0-9]+$ && "$change_request_status" == "pending" ]]; then
  pass "成功创建 workflow_improvement change request #${change_request_id}"
else
  fail "创建 workflow_improvement change request 失败: $change_resp"
fi

change_shadow_initial="$(api_request GET "/change-requests/${change_request_id}/shadow-validation?history_limit=4" "" "local_admin")"
change_gate_initial="$(printf '%s' "$change_shadow_initial" | extract_json_field "change_request.shadow_validation_status" | tr -d '"')"
change_proposal_initial="$(printf '%s' "$change_shadow_initial" | extract_json_field "proposal_shadow_validation_status" | tr -d '"')"
change_ready_initial="$(printf '%s' "$change_shadow_initial" | extract_json_field "change_request.shadow_validation_ready_to_apply" | tr -d '"')"
if [[ "$change_gate_initial" == "required" && "$change_proposal_initial" == "not_started" && "$change_ready_initial" == "false" ]]; then
  pass "change request shadow gate 初始状态正确"
else
  fail "change request shadow 初始状态异常: $change_shadow_initial"
fi

section "Start Async Shadow Validation"
shadow_start_resp="$(python3 - <<'PY' | api_request_stdin POST "/change-requests/${change_request_id}/shadow-validate" "local_admin"
import json
print(json.dumps({
    "note": "stage7 shadow status smoke",
    "await_completion": False,
    "timeout_seconds": 90,
    "poll_interval_seconds": 1.0
}, ensure_ascii=False))
PY
)"
shadow_task_id="$(printf '%s' "$shadow_start_resp" | extract_json_field "shadow_task.id" | tr -d '"')"
shadow_tracking_mode="$(printf '%s' "$shadow_start_resp" | extract_json_field "tracking_mode" | tr -d '"')"
if [[ "$shadow_task_id" =~ ^[0-9]+$ && "$shadow_tracking_mode" == "async_background_wait" ]]; then
  pass "shadow validation 已异步启动 shadow_task_id=${shadow_task_id}"
else
  fail "shadow validation 异步启动异常: $shadow_start_resp"
fi

section "Observe Requested Status"
proposal_shadow_requested="$(api_request GET "/workflow-proposals/${proposal_id}/shadow-validation?history_limit=6" "" "local_admin")"
proposal_requested_status="$(printf '%s' "$proposal_shadow_requested" | extract_json_field "status" | tr -d '"')"
proposal_requested_request_count="$(printf '%s' "$proposal_shadow_requested" | extract_json_field "request_count" | tr -d '"')"
proposal_requested_shadow_task_id="$(printf '%s' "$proposal_shadow_requested" | extract_json_field "latest_shadow_task.id" | tr -d '"')"
if [[ "$proposal_requested_request_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "proposal shadow status 已记录 request_count=${proposal_requested_request_count}"
else
  fail "proposal shadow status 未记录 request: $proposal_shadow_requested"
fi
if [[ "$proposal_requested_status" == "requested" ]]; then
  pass "proposal shadow status 已暴露 requested 中间态"
else
  warn "proposal shadow status 首次查询已不是 requested，当前 status=${proposal_requested_status}"
fi
if [[ "$proposal_requested_shadow_task_id" == "$shadow_task_id" ]]; then
  pass "proposal shadow status 返回的 latest shadow task 与启动响应一致"
else
  fail "proposal latest shadow task 未对齐: $proposal_shadow_requested"
fi

section "Wait Completed Via Status Endpoint"
proposal_shadow_final=""
proposal_final_status=""
for _ in $(seq 1 90); do
  proposal_shadow_final="$(api_request GET "/workflow-proposals/${proposal_id}/shadow-validation?history_limit=8" "" "local_admin")"
  proposal_final_status="$(printf '%s' "$proposal_shadow_final" | extract_json_field "status" | tr -d '"')"
  if [[ "$proposal_final_status" == "completed" ]]; then
    break
  fi
  sleep 1
done

proposal_final_history_count="$(printf '%s' "$proposal_shadow_final" | extract_json_field "history_count" | tr -d '"')"
proposal_final_validation_count="$(printf '%s' "$proposal_shadow_final" | extract_json_field "validation_count" | tr -d '"')"
proposal_final_result="$(printf '%s' "$proposal_shadow_final" | extract_json_field "latest_validation.validation.validation_result" | tr -d '"')"
proposal_final_shadow_task_id="$(printf '%s' "$proposal_shadow_final" | extract_json_field "latest_shadow_task.id" | tr -d '"')"
if [[ "$proposal_final_status" == "completed" ]]; then
  pass "proposal shadow status 最终变为 completed"
else
  fail "proposal shadow status 未在时限内完成: $proposal_shadow_final"
fi
if [[ "$proposal_final_history_count" =~ ^[0-9]+$ && "$proposal_final_history_count" -ge 2 && "$proposal_final_validation_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "proposal shadow 历史已包含 request/result 条目"
else
  fail "proposal shadow 历史条目异常: $proposal_shadow_final"
fi
if [[ "$proposal_final_result" == "matched" || "$proposal_final_result" == "improved" || "$proposal_final_result" == "regressed" || "$proposal_final_result" == "changed" ]]; then
  pass "proposal shadow status 返回可读比较结果 result=${proposal_final_result}"
else
  fail "proposal shadow validation 结果异常: $proposal_shadow_final"
fi
if [[ "$proposal_final_shadow_task_id" == "$shadow_task_id" ]]; then
  pass "proposal shadow 最终 latest shadow task 仍对齐"
else
  fail "proposal shadow 最终 shadow task 未对齐: $proposal_shadow_final"
fi

section "Verify Change Request Shadow Sync"
change_shadow_final="$(api_request GET "/change-requests/${change_request_id}/shadow-validation?history_limit=8" "" "local_admin")"
change_gate_final="$(printf '%s' "$change_shadow_final" | extract_json_field "change_request.shadow_validation_status" | tr -d '"')"
change_ready_final="$(printf '%s' "$change_shadow_final" | extract_json_field "change_request.shadow_validation_ready_to_apply" | tr -d '"')"
change_proposal_final="$(printf '%s' "$change_shadow_final" | extract_json_field "proposal_shadow_validation_status" | tr -d '"')"
change_synced_final="$(printf '%s' "$change_shadow_final" | extract_json_field "latest_validation_synced" | tr -d '"')"
change_report_audit_id="$(printf '%s' "$change_shadow_final" | extract_json_field "change_request.shadow_validation_report.audit_log_id" | tr -d '"')"
change_latest_audit_id="$(printf '%s' "$change_shadow_final" | extract_json_field "latest_validation.audit_log_id" | tr -d '"')"
if [[ "$change_gate_final" == "completed" && "$change_ready_final" == "true" && "$change_proposal_final" == "completed" ]]; then
  pass "change request shadow gate 已同步 completed 并允许 apply"
else
  fail "change request shadow gate 最终状态异常: $change_shadow_final"
fi
if [[ "$change_synced_final" == "true" && "$change_report_audit_id" == "$change_latest_audit_id" && "$change_latest_audit_id" =~ ^[0-9]+$ ]]; then
  pass "change request shadow report 与 proposal 最新 validation 已对齐"
else
  fail "change request shadow report 未对齐最新 validation: $change_shadow_final"
fi

section "Done"
log "日志文件: $LOG_FILE"
log "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT} WARN=${WARN_COUNT}"

if (( FAIL_COUNT > 0 )); then
  exit 1
fi
