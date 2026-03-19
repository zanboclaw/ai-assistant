#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-${ROOT_DIR}/logs}"
API_BASE="${API_BASE:-http://127.0.0.1:8000}"
mkdir -p "$LOG_DIR"
source "${ROOT_DIR}/scripts/http_fallback.sh"

TS="$(date +%F_%H%M%S)"
LOG_FILE="${LOG_DIR}/stage6_evaluator_check_${TS}.log"

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

section "Create Mainline Evaluator Task"
task_resp="$(python3 - <<'PY' | api_request_stdin POST "/tasks" "local_admin"
import json
print(json.dumps({
    "user_input": "读取 JSON 文件 /workspace/sample.json 并整理要点"
}, ensure_ascii=False))
PY
)"
task_id="$(printf '%s' "$task_resp" | extract_json_field "id" | tr -d '"')"
if [[ "$task_id" =~ ^[0-9]+$ ]]; then
  pass "成功创建 mainline evaluator smoke task #$task_id"
else
  fail "创建 mainline evaluator smoke task 失败: $task_resp"
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
  pass "mainline evaluator task 进入可观测状态 status=${task_status}"
else
  fail "mainline evaluator task 未进入可观测状态: $task_state"
fi

section "Approve Pending Task If Needed"
approval_done="false"
if [[ "$task_status" == "waiting_approval" ]]; then
  approvals_resp="$(api_request GET "/tasks/${task_id}/approvals")"
  approval_id="$(printf '%s' "$approvals_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); pending=next((item for item in data if item.get("status")=="pending"), {}); print(pending.get("id") or "")')"
  if [[ "$approval_id" =~ ^[0-9]+$ ]]; then
    approve_resp="$(api_request POST "/approvals/${approval_id}/approve" '{"note":"stage6 evaluator mainline smoke approve"}' "local_admin")"
    if echo "$approve_resp" | grep -q '"approval approved"'; then
      pass "已批准 evaluator task 审批 approval_id=${approval_id}"
      approval_done="true"
    else
      fail "evaluator task 审批批准异常: ${approve_resp}"
    fi
  else
    fail "未找到 evaluator task 待批准 approval: ${approvals_resp}"
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
      approve_resp="$(api_request POST "/approvals/${approval_id}/approve" '{"note":"stage6 evaluator mainline smoke approve"}' "local_admin")"
      if echo "$approve_resp" | grep -q '"approval approved"'; then
        pass "等待终态期间已批准 evaluator task 审批 approval_id=${approval_id}"
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
  pass "mainline evaluator task 进入终态 status=${task_status}"
else
  fail "mainline evaluator task 未进入终态: ${task_state}"
fi

section "Verify Evaluator APIs"
latest_eval_resp="$(api_request GET "/tasks/${task_id}/evaluator-runs/latest")"
evaluator_run_id="$(printf '%s' "$latest_eval_resp" | extract_json_field "id" | tr -d '"')"
latest_eval_decision="$(printf '%s' "$latest_eval_resp" | extract_json_field "decision" | tr -d '"')"
latest_eval_score="$(printf '%s' "$latest_eval_resp" | extract_json_field "score" | tr -d '"')"
latest_eval_source="$(printf '%s' "$latest_eval_resp" | extract_json_field "source" | tr -d '"')"
latest_eval_failure_reason="$(printf '%s' "$latest_eval_resp" | extract_json_field "failure_reason" | tr -d '"')"
latest_eval_failure_stage="$(printf '%s' "$latest_eval_resp" | extract_json_field "failure_stage" | tr -d '"')"
latest_eval_proposal_action="$(printf '%s' "$latest_eval_resp" | extract_json_field "workflow_proposal.action_key" | tr -d '"')"
if [[ "$evaluator_run_id" =~ ^[0-9]+$ && "$latest_eval_decision" == "approved" && "$latest_eval_score" =~ ^[0-9]+$ && "$latest_eval_source" == "task_runtime_postrun_v1" && "$latest_eval_failure_reason" == "none" && "$latest_eval_failure_stage" == "none" && "$latest_eval_proposal_action" == "expand_specialist_scope" ]]; then
  pass "mainline latest evaluator 接口返回决策、评分、来源、failure taxonomy 和 workflow proposal"
else
  fail "mainline latest evaluator 接口返回异常: $latest_eval_resp"
fi

evaluator_list_resp="$(api_request GET "/evaluator-runs?task_id=${task_id}&limit=5")"
evaluator_list_count="$(printf '%s' "$evaluator_list_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(len(data))')"
if [[ "$evaluator_list_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "evaluator-runs 列表接口可用"
else
  fail "evaluator-runs 列表为空或异常: $evaluator_list_resp"
fi

task_summary_resp="$(api_request GET "/tasks/${task_id}/agent-runs/summary")"
summary_eval_id="$(printf '%s' "$task_summary_resp" | extract_json_field "latest_evaluator.id" | tr -d '"')"
summary_failure_reason="$(printf '%s' "$task_summary_resp" | extract_json_field "latest_failure_reason" | tr -d '"')"
summary_failure_stage="$(printf '%s' "$task_summary_resp" | extract_json_field "latest_failure_stage" | tr -d '"')"
summary_proposal_action="$(printf '%s' "$task_summary_resp" | extract_json_field "latest_workflow_proposal.action_key" | tr -d '"')"
if [[ "$summary_eval_id" == "$evaluator_run_id" && "$summary_failure_reason" == "none" && "$summary_failure_stage" == "none" && "$summary_proposal_action" == "expand_specialist_scope" ]]; then
  pass "task 级 agent summary 暴露 latest_evaluator、failure taxonomy 和 workflow proposal"
else
  fail "task 级 agent summary 未暴露 latest_evaluator: $task_summary_resp"
fi

proposal_resp="$(api_request GET "/tasks/${task_id}/workflow-proposals/latest")"
proposal_action="$(printf '%s' "$proposal_resp" | extract_json_field "action_key" | tr -d '"')"
proposal_priority="$(printf '%s' "$proposal_resp" | extract_json_field "priority" | tr -d '"')"
if [[ "$proposal_action" == "expand_specialist_scope" && "$proposal_priority" == "low" ]]; then
  pass "workflow proposal latest 接口可用"
else
  fail "workflow proposal latest 接口异常: $proposal_resp"
fi

proposal_list_resp="$(api_request GET "/workflow-proposals?task_id=${task_id}&limit=5")"
proposal_list_count="$(printf '%s' "$proposal_list_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(len(data))')"
proposal_list_action="$(printf '%s' "$proposal_list_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print((data[0].get("action_key") if data else ""))')"
if [[ "$proposal_list_count" =~ ^[1-9][0-9]*$ && "$proposal_list_action" == "expand_specialist_scope" ]]; then
  pass "workflow proposals 列表接口可用"
else
  fail "workflow proposals 列表接口异常: $proposal_list_resp"
fi

task_proposal_list_resp="$(api_request GET "/tasks/${task_id}/workflow-proposals?limit=5")"
task_proposal_list_count="$(printf '%s' "$task_proposal_list_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(len(data))')"
if [[ "$task_proposal_list_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "task 维度 workflow proposals 列表接口可用"
else
  fail "task 维度 workflow proposals 列表接口异常: $task_proposal_list_resp"
fi

proposal_id="$(printf '%s' "$proposal_resp" | extract_json_field "id" | tr -d '"')"
proposal_draft_resp="$(api_request GET "/workflow-proposals/${proposal_id}/change-request-draft")"
proposal_draft_ready="$(printf '%s' "$proposal_draft_resp" | extract_json_field "bridge_ready" | tr -d '"')"
proposal_draft_action="$(printf '%s' "$proposal_draft_resp" | extract_json_field "source_workflow_proposal.action_key" | tr -d '"')"
proposal_draft_target_type="$(printf '%s' "$proposal_draft_resp" | extract_json_field "target_type" | tr -d '"')"
proposal_draft_target_key="$(printf '%s' "$proposal_draft_resp" | extract_json_field "target_key" | tr -d '"')"
proposal_draft_suggestion_source="$(printf '%s' "$proposal_draft_resp" | extract_json_field "suggestion_source" | tr -d '"')"
if [[ "$proposal_draft_ready" == "true" && "$proposal_draft_action" == "expand_specialist_scope" && "$proposal_draft_target_type" == "model_route" && "$proposal_draft_target_key" == "planner" && "$proposal_draft_suggestion_source" == "auto_action_mapping" ]]; then
  pass "workflow proposal change-request draft 预览接口返回自动映射建议"
else
  fail "workflow proposal change-request draft 预览异常: $proposal_draft_resp"
fi

bridge_actor_name="wf_bridge_actor_${task_id}"
bridge_create_resp="$(BRIDGE_ACTOR_NAME="$bridge_actor_name" python3 - <<'PY' | api_request_stdin POST "/workflow-proposals/${proposal_id}/change-request-draft" "local_admin"
import json, os
print(json.dumps({
    "target_type": "access_actor",
    "target_key": os.environ["BRIDGE_ACTOR_NAME"],
    "proposed_payload": {
        "role": "viewer",
        "description": "workflow proposal bridge smoke actor"
    },
    "rationale": "stage6 workflow proposal bridge smoke"
}, ensure_ascii=False))
PY
)"
bridge_change_request_id="$(printf '%s' "$bridge_create_resp" | extract_json_field "change_request.id" | tr -d '"')"
bridge_change_request_status="$(printf '%s' "$bridge_create_resp" | extract_json_field "change_request.status" | tr -d '"')"
bridge_change_request_rationale="$(printf '%s' "$bridge_create_resp" | extract_json_field "change_request.rationale" | tr -d '"')"
if [[ "$bridge_change_request_id" =~ ^[0-9]+$ && "$bridge_change_request_status" == "pending" && "$bridge_change_request_rationale" == *"workflow proposal #${proposal_id}"* ]]; then
  pass "workflow proposal 能桥接生成 pending change request"
else
  fail "workflow proposal 桥接 change request 异常: $bridge_create_resp"
fi

section "Verify Monitor And Audit"
monitor_resp="$(api_request GET "/monitor/overview")"
monitor_total_eval="$(printf '%s' "$monitor_resp" | extract_json_field "evaluator_metrics.total_evaluator_runs" | tr -d '"')"
monitor_recent_eval_count="$(printf '%s' "$monitor_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(len(data.get("recent_evaluator_runs") or []))')"
monitor_reason_none="$(printf '%s' "$monitor_resp" | extract_json_field "evaluator_metrics.runs_by_reason.none" | tr -d '"')"
monitor_total_proposals="$(printf '%s' "$monitor_resp" | extract_json_field "evaluator_metrics.total_workflow_proposals" | tr -d '"')"
monitor_proposal_action="$(printf '%s' "$monitor_resp" | extract_json_field "evaluator_metrics.workflow_proposals_by_action.expand_specialist_scope" | tr -d '"')"
monitor_recent_proposal_count="$(printf '%s' "$monitor_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(len(data.get("recent_workflow_proposals") or []))')"
if [[ "$monitor_total_eval" =~ ^[1-9][0-9]*$ && "$monitor_recent_eval_count" =~ ^[1-9][0-9]*$ && "$monitor_reason_none" =~ ^[1-9][0-9]*$ && "$monitor_total_proposals" =~ ^[1-9][0-9]*$ && "$monitor_proposal_action" =~ ^[1-9][0-9]*$ && "$monitor_recent_proposal_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "monitor/overview 返回 evaluator 聚合、proposal 聚合和 recent 列表"
else
  fail "monitor/overview 未返回 evaluator 聚合: $monitor_resp"
fi

audit_resp="$(api_request GET "/audit-logs?event_type=evaluator.recorded&limit=5")"
audit_match="$(printf '%s' "$audit_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(any(item.get("task_id")=='"$task_id"' for item in data))')"
if [[ "$audit_match" == "True" ]]; then
  pass "audit log 记录了 evaluator.recorded"
else
  fail "audit log 未记录 evaluator.recorded: $audit_resp"
fi

bridge_audit_resp="$(api_request GET "/audit-logs?event_type=workflow_proposal.change_request_create&limit=5")"
bridge_audit_match="$(printf '%s' "$bridge_audit_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(any((item.get("details") or {}).get("proposal_id")=='"$proposal_id"' for item in data))')"
if [[ "$bridge_audit_match" == "True" ]]; then
  pass "audit log 记录了 workflow proposal -> change request bridge"
else
  fail "audit log 未记录 workflow proposal -> change request bridge: $bridge_audit_resp"
fi

section "Verify Failure Taxonomy On Rejected Path"
failed_task_resp="$(python3 - <<'PY' | api_request_stdin POST "/tasks" "local_admin"
import json
print(json.dumps({
    "user_input": "Stage 6 evaluator failed path smoke"
}, ensure_ascii=False))
PY
)"
failed_task_id="$(printf '%s' "$failed_task_resp" | extract_json_field "id" | tr -d '"')"
if [[ "$failed_task_id" =~ ^[0-9]+$ ]]; then
  pass "成功创建失败路径 task #$failed_task_id"
else
  fail "创建失败路径 task 失败: $failed_task_resp"
fi

for _ in $(seq 1 40); do
  failed_task_state="$(api_request GET "/tasks/${failed_task_id}" || true)"
  failed_task_status="$(printf '%s' "$failed_task_state" | extract_json_field "status" | tr -d '"' || true)"
  if [[ "$failed_task_status" == "failed" ]]; then
    break
  fi
  sleep 1
done

if [[ "$failed_task_status" == "failed" ]]; then
  pass "失败路径 task 自动进入 failed"
else
  fail "失败路径 task 未进入 failed: $failed_task_state"
fi

failed_latest_eval_resp="$(api_request GET "/tasks/${failed_task_id}/evaluator-runs/latest")"
failed_eval_id="$(printf '%s' "$failed_latest_eval_resp" | extract_json_field "id" | tr -d '"')"
failed_eval_source="$(printf '%s' "$failed_latest_eval_resp" | extract_json_field "source" | tr -d '"')"
failed_eval_decision="$(printf '%s' "$failed_latest_eval_resp" | extract_json_field "decision" | tr -d '"')"
failed_eval_reason="$(printf '%s' "$failed_latest_eval_resp" | extract_json_field "failure_reason" | tr -d '"')"
failed_eval_stage="$(printf '%s' "$failed_latest_eval_resp" | extract_json_field "failure_stage" | tr -d '"')"
failed_eval_proposal_action="$(printf '%s' "$failed_latest_eval_resp" | extract_json_field "workflow_proposal.action_key" | tr -d '"')"
if [[ "$failed_eval_id" =~ ^[0-9]+$ && "$failed_eval_source" == "task_runtime_postrun_v1" && "$failed_eval_decision" == "rejected" && "$failed_eval_reason" == "task_failed_step" && "$failed_eval_stage" == "execution" && "$failed_eval_proposal_action" == "repair_failed_steps" ]]; then
  pass "失败路径主链 postrun 返回 rejected evaluator taxonomy 和 workflow proposal"
else
  fail "失败路径主链 postrun evaluator 异常: $failed_latest_eval_resp"
fi

failed_summary_resp="$(api_request GET "/tasks/${failed_task_id}/agent-runs/summary")"
failed_summary_status="$(printf '%s' "$failed_summary_resp" | extract_json_field "implementation_status" | tr -d '"')"
failed_summary_backend="$(printf '%s' "$failed_summary_resp" | extract_json_field "execution_backend" | tr -d '"')"
if [[ "$failed_summary_status" == "task_runtime_postrun_v1" && "$failed_summary_backend" == "mainline" ]]; then
  pass "失败路径 task summary 标记 Stage 5/6 已进入主链 postrun"
else
  fail "失败路径 task summary 未标记主链 postrun: $failed_summary_resp"
fi

failed_bootstrap_result="$(python3 - <<'PY' | api_request_stdin_with_status POST "/tasks/${failed_task_id}/agent-runs/bootstrap-demo" "local_admin"
import json
print(json.dumps({
    "objective": "Bootstrap failed path evaluator smoke",
    "specialist_count": 2,
    "include_reviewer": True,
    "note": "stage6 evaluator failed path"
}, ensure_ascii=False))
PY
)"
failed_bootstrap_status="$(printf '%s' "$failed_bootstrap_result" | sed -n '1p')"
failed_bootstrap_resp="$(printf '%s' "$failed_bootstrap_result" | sed '1d')"
if [[ "$failed_bootstrap_status" == "409" && "$failed_bootstrap_resp" == *"Task already has agent runs; bootstrap-demo is single-use per task"* ]]; then
  pass "失败路径 bootstrap-demo 会因主链 postrun 已存在而拒绝重复写入"
else
  fail "失败路径 bootstrap-demo 单次写入保护异常 status=${failed_bootstrap_status} body=${failed_bootstrap_resp}"
fi

failed_finalize_result="$(python3 - <<'PY' | api_request_stdin_with_status POST "/tasks/${failed_task_id}/agent-runs/finalize-demo" "local_admin"
import json
print(json.dumps({
    "summary": "Finalize failed evaluator smoke",
    "note": "stage6 evaluator failed finalize",
    "reviewer_decision": "auto"
}, ensure_ascii=False))
PY
)"
failed_finalize_status="$(printf '%s' "$failed_finalize_result" | sed -n '1p')"
failed_finalize_resp="$(printf '%s' "$failed_finalize_result" | sed '1d')"
if [[ "$failed_finalize_status" == "409" && "$failed_finalize_resp" == *"Task already has a final artifact; finalize-demo is single-use per task"* ]]; then
  pass "失败路径 finalize-demo 会因主链 postrun final artifact 已存在而拒绝重复写入"
else
  fail "失败路径 finalize-demo 单次写入保护异常 status=${failed_finalize_status} body=${failed_finalize_resp}"
fi

section "Done"
log "日志文件: $LOG_FILE"
log "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT} WARN=${WARN_COUNT}"

if (( FAIL_COUNT > 0 )); then
  exit 1
fi
