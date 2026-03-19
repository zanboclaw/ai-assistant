#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-${ROOT_DIR}/logs}"
API_BASE="${API_BASE:-http://127.0.0.1:8000}"
mkdir -p "$LOG_DIR"
source "${ROOT_DIR}/scripts/http_fallback.sh"

TS="$(date +%F_%H%M%S)"
LOG_FILE="${LOG_DIR}/workflow_proposal_bridge_check_${TS}.log"

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

section "Create Mainline Workflow Proposal Task"
task_resp="$(python3 - <<'PY' | api_request_stdin POST "/tasks" "local_admin"
import json
print(json.dumps({
    "user_input": "读取 JSON 文件 /workspace/sample.json 并整理要点"
}, ensure_ascii=False))
PY
)"
task_id="$(printf '%s' "$task_resp" | extract_json_field "id" | tr -d '"')"
if [[ "$task_id" =~ ^[0-9]+$ ]]; then
  pass "成功创建 mainline bridge smoke task #$task_id"
else
  fail "创建 mainline bridge smoke task 失败: $task_resp"
fi

section "Wait Running Or Approval"
task_status=""
task_state=""
for _ in $(seq 1 30); do
  task_state="$(api_request GET "/tasks/${task_id}")"
  task_status="$(printf '%s' "$task_state" | extract_json_field "status" | tr -d '"')"
  if [[ "$task_status" == "waiting_approval" || "$task_status" == "running" || "$task_status" == "completed" || "$task_status" == "failed" ]]; then
    break
  fi
  sleep 1
done

if [[ "$task_status" == "waiting_approval" || "$task_status" == "running" || "$task_status" == "completed" || "$task_status" == "failed" ]]; then
  pass "mainline bridge task 进入可观测状态 status=${task_status}"
else
  fail "mainline bridge task 未进入可观测状态: $task_state"
fi

section "Approve Pending Task If Needed"
approval_done="false"
if [[ "$task_status" == "waiting_approval" ]]; then
  approvals_resp="$(api_request GET "/tasks/${task_id}/approvals")"
  approval_id="$(printf '%s' "$approvals_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); pending=next((item for item in data if item.get("status")=="pending"), {}); print(pending.get("id") or "")')"
  if [[ "$approval_id" =~ ^[0-9]+$ ]]; then
    approve_resp="$(api_request POST "/approvals/${approval_id}/approve" '{"note":"workflow proposal bridge mainline smoke approve"}' "local_admin")"
    if echo "$approve_resp" | grep -q '"approval approved"'; then
      pass "已批准 bridge task 审批 approval_id=${approval_id}"
      approval_done="true"
    else
      fail "bridge task 审批批准异常: ${approve_resp}"
    fi
  else
    fail "未找到 bridge task 待批准 approval: ${approvals_resp}"
  fi
fi

section "Wait Terminal Status"
for _ in $(seq 1 40); do
  task_state="$(api_request GET "/tasks/${task_id}")"
  task_status="$(printf '%s' "$task_state" | extract_json_field "status" | tr -d '"')"
  if [[ "$task_status" == "waiting_approval" && "$approval_done" != "true" ]]; then
    approvals_resp="$(api_request GET "/tasks/${task_id}/approvals")"
    approval_id="$(printf '%s' "$approvals_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); pending=next((item for item in data if item.get("status")=="pending"), {}); print(pending.get("id") or "")')"
    if [[ "$approval_id" =~ ^[0-9]+$ ]]; then
      approve_resp="$(api_request POST "/approvals/${approval_id}/approve" '{"note":"workflow proposal bridge mainline smoke approve"}' "local_admin")"
      if echo "$approve_resp" | grep -q '"approval approved"'; then
        pass "等待终态期间已批准 bridge task 审批 approval_id=${approval_id}"
        approval_done="true"
      else
        fail "等待终态期间审批批准异常: ${approve_resp}"
      fi
    fi
  fi
  if [[ "$task_status" == "completed" || "$task_status" == "failed" ]]; then
    break
  fi
  sleep 1
done

if [[ "$task_status" == "completed" || "$task_status" == "failed" ]]; then
  pass "mainline bridge task 进入终态 status=${task_status}"
else
  fail "mainline bridge task 未进入终态: ${task_state}"
fi

summary_resp="$(api_request GET "/tasks/${task_id}/agent-runs/summary")"
summary_impl="$(printf '%s' "$summary_resp" | extract_json_field "implementation_status" | tr -d '"')"
summary_backend="$(printf '%s' "$summary_resp" | extract_json_field "execution_backend" | tr -d '"')"
summary_eval_source="$(printf '%s' "$summary_resp" | extract_json_field "latest_evaluator_source" | tr -d '"')"
summary_proposal_action="$(printf '%s' "$summary_resp" | extract_json_field "latest_workflow_proposal.action_key" | tr -d '"')"
if [[ "$summary_impl" == "task_runtime_postrun_v1" && "$summary_backend" == "mainline" && "$summary_eval_source" == "task_runtime_postrun_v1" && "$summary_proposal_action" == "expand_specialist_scope" ]]; then
  pass "bridge smoke task 已通过主链产出 workflow proposal"
else
  fail "bridge smoke task 未产出预期主链 proposal: $summary_resp"
fi

proposal_resp="$(api_request GET "/tasks/${task_id}/workflow-proposals/latest")"
proposal_id="$(printf '%s' "$proposal_resp" | extract_json_field "id" | tr -d '"')"
proposal_source="$(printf '%s' "$proposal_resp" | extract_json_field "source" | tr -d '"')"
if [[ "$proposal_id" =~ ^[0-9]+$ && "$proposal_source" == "task_runtime_postrun_v1" ]]; then
  pass "主链 workflow proposal latest 接口返回 proposal id"
else
  fail "主链 workflow proposal latest 接口异常: $proposal_resp"
fi

section "Preview Bridge Draft"
draft_resp="$(api_request GET "/workflow-proposals/${proposal_id}/change-request-draft")"
draft_ready="$(printf '%s' "$draft_resp" | extract_json_field "bridge_ready" | tr -d '"')"
draft_target_type="$(printf '%s' "$draft_resp" | extract_json_field "target_type" | tr -d '"')"
draft_target_key="$(printf '%s' "$draft_resp" | extract_json_field "target_key" | tr -d '"')"
draft_suggestion_source="$(printf '%s' "$draft_resp" | extract_json_field "suggestion_source" | tr -d '"')"
if [[ "$draft_ready" == "true" && "$draft_target_type" == "model_route" && "$draft_target_key" == "planner" && "$draft_suggestion_source" == "auto_action_mapping" ]]; then
  pass "change-request draft 预览返回自动 model_route 建议"
else
  fail "change-request draft 预览异常: $draft_resp"
fi

section "Create And Apply Change Request"
change_resp="$(python3 - <<'PY' | api_request_stdin POST "/workflow-proposals/${proposal_id}/change-request-draft" "local_admin"
import json
print(json.dumps({
    "target_type": "model_route",
    "target_key": "planner",
    "proposed_payload": {
        "provider": "deepseek_default",
        "model_name": "deepseek-chat",
        "temperature": 0.2,
        "max_tokens": 1800,
        "enabled": True,
        "description": "workflow proposal bridge smoke route"
    },
    "rationale": "workflow proposal bridge smoke create-change"
}, ensure_ascii=False))
PY
)"
change_request_id="$(printf '%s' "$change_resp" | extract_json_field "change_request.id" | tr -d '"')"
change_request_status="$(printf '%s' "$change_resp" | extract_json_field "change_request.status" | tr -d '"')"
if [[ "$change_request_id" =~ ^[0-9]+$ && "$change_request_status" == "pending" ]]; then
  pass "workflow proposal 成功创建 pending change request"
else
  fail "workflow proposal 创建 change request 失败: $change_resp"
fi

approve_resp="$(api_request POST "/change-requests/${change_request_id}/approve" '{"note":"workflow proposal bridge approve"}' "local_admin")"
approved_status="$(printf '%s' "$approve_resp" | extract_json_field "status" | tr -d '"')"
if [[ "$approved_status" == "approved" ]]; then
  pass "change request 已批准"
else
  fail "change request 批准异常: $approve_resp"
fi

apply_resp="$(api_request POST "/change-requests/${change_request_id}/apply" "" "local_admin")"
applied_status="$(printf '%s' "$apply_resp" | extract_json_field "status" | tr -d '"')"
if [[ "$applied_status" == "applied" ]]; then
  pass "change request 已应用"
else
  fail "change request 应用异常: $apply_resp"
fi

section "Verify Audit And Listing"
audit_resp="$(api_request GET "/audit-logs?event_type=workflow_proposal.change_request_create&limit=10")"
audit_match="$(printf '%s' "$audit_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(any((item.get("details") or {}).get("proposal_id")=='"$proposal_id"' for item in data))')"
if [[ "$audit_match" == "True" ]]; then
  pass "audit log 记录了 proposal bridge"
else
  fail "audit log 未记录 proposal bridge: $audit_resp"
fi

proposal_list_resp="$(api_request GET "/workflow-proposals?action_key=expand_specialist_scope&limit=10")"
proposal_list_count="$(printf '%s' "$proposal_list_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(len(data))')"
if [[ "$proposal_list_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "workflow-proposals 支持按 action_key 过滤"
else
  fail "workflow-proposals action_key 过滤异常: $proposal_list_resp"
fi

section "Done"
log "日志文件: $LOG_FILE"
log "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT} WARN=${WARN_COUNT}"

if (( FAIL_COUNT > 0 )); then
  exit 1
fi
