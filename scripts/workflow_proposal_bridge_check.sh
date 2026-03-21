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

select_change_request_by_id() {
  local change_request_id="$1"
  python3 -c 'import json, sys
target = int(sys.argv[1])
data = json.load(sys.stdin)
item = next((entry for entry in data if int(entry.get("id") or 0) == target), {})
print(json.dumps(item, ensure_ascii=False))' "$change_request_id"
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
for _ in $(seq 1 90); do
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
draft_patch_summary="$(printf '%s' "$draft_resp" | extract_json_field "patch_summary" | tr -d '"')"
draft_patch_format="$(printf '%s' "$draft_resp" | extract_json_field "payload_patch.format" | tr -d '"')"
draft_patch_changed_key_count="$(printf '%s' "$draft_resp" | extract_json_field "payload_patch.changed_key_count" | tr -d '"')"
draft_baseline_provider="$(printf '%s' "$draft_resp" | extract_json_field "baseline_payload.provider" | tr -d '"')"
if [[ "$draft_ready" == "true" && "$draft_target_type" == "model_route" && "$draft_target_key" == "planner" && "$draft_suggestion_source" == "auto_action_mapping" ]]; then
  pass "change-request draft 预览返回自动 model_route 建议"
else
  fail "change-request draft 预览异常: $draft_resp"
fi
if [[ -n "$draft_patch_summary" && "$draft_patch_format" == "json_object_diff_v1" && "$draft_patch_changed_key_count" =~ ^[0-9]+$ && "$draft_patch_changed_key_count" -ge 0 && -n "$draft_baseline_provider" ]]; then
  pass "bridge draft 已暴露 patch artifact（baseline/payload_patch/patch_summary）"
else
  fail "bridge draft patch artifact 字段异常: $draft_resp"
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
change_request_patch_summary="$(printf '%s' "$change_resp" | extract_json_field "change_request.patch_summary" | tr -d '"')"
change_request_patch_format="$(printf '%s' "$change_resp" | extract_json_field "change_request.payload_patch.format" | tr -d '"')"
change_request_patch_changed_key_count="$(printf '%s' "$change_resp" | extract_json_field "change_request.payload_patch.changed_key_count" | tr -d '"')"
change_request_baseline_provider="$(printf '%s' "$change_resp" | extract_json_field "change_request.baseline_payload.provider" | tr -d '"')"
if [[ "$change_request_id" =~ ^[0-9]+$ && "$change_request_status" == "pending" ]]; then
  pass "workflow proposal 成功创建 pending change request"
else
  fail "workflow proposal 创建 change request 失败: $change_resp"
fi
if [[ -n "$change_request_patch_summary" && "$change_request_patch_format" == "json_object_diff_v1" && "$change_request_patch_changed_key_count" =~ ^[0-9]+$ && "$change_request_patch_changed_key_count" -ge 0 && -n "$change_request_baseline_provider" ]]; then
  pass "bridge create-change 返回 change request patch artifact"
else
  fail "bridge create-change 缺少 patch artifact: $change_resp"
fi

change_request_alt_resp="$(python3 - <<'PY' | api_request_stdin POST "/workflow-proposals/${proposal_id}/change-request-draft" "local_admin"
import json
print(json.dumps({
    "target_type": "model_route",
    "target_key": "planner",
    "proposed_payload": {
        "provider": "deepseek_default",
        "model_name": "deepseek-chat",
        "temperature": 0.2,
        "max_tokens": 1901,
        "enabled": True,
        "description": "workflow proposal bridge smoke route alt"
    },
    "rationale": "workflow proposal bridge smoke create-change alt"
}, ensure_ascii=False))
PY
)"
change_request_alt_id="$(printf '%s' "$change_request_alt_resp" | extract_json_field "change_request.id" | tr -d '"')"
change_request_alt_status="$(printf '%s' "$change_request_alt_resp" | extract_json_field "change_request.status" | tr -d '"')"
if [[ "$change_request_alt_id" =~ ^[0-9]+$ && "$change_request_alt_status" == "pending" ]]; then
  pass "workflow proposal 成功创建第二张不同 payload 的 pending change request"
else
  fail "workflow proposal 创建第二张 change request 失败: $change_request_alt_resp"
fi

approve_resp="$(api_request POST "/change-requests/${change_request_id}/approve" '{"note":"workflow proposal bridge approve"}' "local_admin")"
approved_status="$(printf '%s' "$approve_resp" | extract_json_field "status" | tr -d '"')"
if [[ "$approved_status" == "approved" ]]; then
  pass "change request 已批准"
else
  fail "change request 批准异常: $approve_resp"
fi

approve_alt_resp="$(api_request POST "/change-requests/${change_request_alt_id}/approve" '{"note":"workflow proposal bridge approve alt"}' "local_admin")"
approved_alt_status="$(printf '%s' "$approve_alt_resp" | extract_json_field "status" | tr -d '"')"
if [[ "$approved_alt_status" == "approved" ]]; then
  pass "第二张 change request 已批准"
else
  fail "第二张 change request 批准异常: $approve_alt_resp"
fi

change_show_resp="$(api_request GET "/change-requests?proposal_kind=workflow_improvement" "" "local_admin" | select_change_request_by_id "$change_request_id")"
change_proposal_kind="$(printf '%s' "$change_show_resp" | extract_json_field "proposal_kind" | tr -d '"')"
change_shadow_validation_status="$(printf '%s' "$change_show_resp" | extract_json_field "shadow_validation_status" | tr -d '"')"
change_source_workflow_proposal_id="$(printf '%s' "$change_show_resp" | extract_json_field "source_workflow_proposal_id" | tr -d '"')"
if [[ "$change_proposal_kind" == "workflow_improvement" && "$change_shadow_validation_status" == "required" && "$change_source_workflow_proposal_id" =~ ^[0-9]+$ ]]; then
  pass "workflow_improvement change request 初始即要求 shadow validation"
else
  fail "workflow_improvement shadow validation 初始状态异常: ${change_show_resp}"
fi

change_alt_show_resp="$(api_request GET "/change-requests?proposal_kind=workflow_improvement" "" "local_admin" | select_change_request_by_id "$change_request_alt_id")"
change_alt_shadow_validation_status="$(printf '%s' "$change_alt_show_resp" | extract_json_field "shadow_validation_status" | tr -d '"')"
if [[ "$change_alt_shadow_validation_status" == "required" ]]; then
  pass "第二张 workflow_improvement change request 初始也要求 shadow validation"
else
  fail "第二张 workflow_improvement shadow validation 初始状态异常: ${change_alt_show_resp}"
fi

apply_gate_resp="$(api_request_with_status POST "/change-requests/${change_request_id}/apply" "" "local_admin")"
apply_gate_status="$(printf '%s' "$apply_gate_resp" | head -n1 | tr -d '\r')"
apply_gate_body="$(printf '%s' "$apply_gate_resp" | sed '1d')"
apply_gate_detail="$(printf '%s' "$apply_gate_body" | extract_json_field "detail" | tr -d '"')"
if [[ "$apply_gate_status" == "409" && "$apply_gate_detail" == *"shadow validation"* ]]; then
  pass "change request 在 shadow validation 前被 apply gate 正确拦截"
else
  fail "change request 未被 shadow validation gate 拦截: ${apply_gate_resp}"
fi

section "Run Change-Scoped Shadow Validation"
shadow_resp="$(python3 - <<'PY' | api_request_stdin POST "/change-requests/${change_request_id}/shadow-validate" "local_admin"
import json
print(json.dumps({
    "note": "workflow proposal bridge gate validation exact candidate",
    "await_completion": True,
    "timeout_seconds": 90,
    "poll_interval_seconds": 1.0
}, ensure_ascii=False))
PY
)"
shadow_task_id="$(printf '%s' "$shadow_resp" | extract_json_field "shadow_task.id" | tr -d '"')"
shadow_completed="$(printf '%s' "$shadow_resp" | extract_json_field "completed" | tr -d '"')"
shadow_eval_id="$(printf '%s' "$shadow_resp" | extract_json_field "shadow_evaluator.id" | tr -d '"')"
shadow_validation_result="$(printf '%s' "$shadow_resp" | extract_json_field "validation.validation_result" | tr -d '"')"
shadow_validation_mode="$(printf '%s' "$shadow_resp" | extract_json_field "validation.validation_mode" | tr -d '"')"
shadow_candidate_target_key="$(printf '%s' "$shadow_resp" | extract_json_field "validation.candidate_overlay.target_key" | tr -d '"')"
shadow_candidate_payload_hash="$(printf '%s' "$shadow_resp" | extract_json_field "validation.candidate_overlay.payload_hash" | tr -d '"')"
shadow_runtime_override_tokens="$(printf '%s' "$shadow_resp" | extract_json_field "validation.shadow_runtime_overrides.model_route_overrides.planner.max_tokens" | tr -d '"')"
if [[ "$shadow_completed" == "true" && "$shadow_task_id" =~ ^[0-9]+$ && "$shadow_eval_id" =~ ^[0-9]+$ ]]; then
  pass "change-scoped shadow validation 已完成 shadow_task_id=${shadow_task_id}"
else
  fail "change-scoped shadow validation 未完成: $shadow_resp"
fi
if [[ "$shadow_validation_result" == "matched" || "$shadow_validation_result" == "improved" || "$shadow_validation_result" == "regressed" || "$shadow_validation_result" == "changed" ]]; then
  pass "change-scoped shadow validation 产出了可读比较结果 result=${shadow_validation_result}"
else
  fail "change-scoped shadow validation 比较结果异常: $shadow_resp"
fi
if [[ "$shadow_validation_mode" == "candidate_overlay_compare" && "$shadow_candidate_target_key" == "planner" && "$shadow_candidate_payload_hash" != "" && "$shadow_runtime_override_tokens" == "1800" ]]; then
  pass "shadow validation 已按 candidate overlay 注入 planner route"
else
  fail "shadow validation candidate overlay 未正确注入: $shadow_resp"
fi

change_after_shadow_resp="$(api_request GET "/change-requests?proposal_kind=workflow_improvement" "" "local_admin" | select_change_request_by_id "$change_request_id")"
change_after_shadow_status="$(printf '%s' "$change_after_shadow_resp" | extract_json_field "shadow_validation_status" | tr -d '"')"
change_after_shadow_ready="$(printf '%s' "$change_after_shadow_resp" | extract_json_field "shadow_validation_ready_to_apply" | tr -d '"')"
change_after_shadow_result="$(printf '%s' "$change_after_shadow_resp" | extract_json_field "shadow_validation_report.validation.validation_result" | tr -d '"')"
change_after_shadow_match="$(printf '%s' "$change_after_shadow_resp" | extract_json_field "shadow_validation_candidate_match" | tr -d '"')"
change_after_shadow_hash="$(printf '%s' "$change_after_shadow_resp" | extract_json_field "proposed_payload_hash" | tr -d '"')"
change_after_shadow_report_hash="$(printf '%s' "$change_after_shadow_resp" | extract_json_field "shadow_validation_report.validation.candidate_overlay.payload_hash" | tr -d '"')"
if [[ "$change_after_shadow_status" == "completed" && "$change_after_shadow_ready" == "true" && "$change_after_shadow_match" == "true" ]]; then
  pass "目标 change request 已同步记录精确 payload 的 shadow validation"
else
  fail "change request 未同步 shadow validation 状态: $change_after_shadow_resp"
fi
if [[ "$change_after_shadow_result" == "$shadow_validation_result" && "$change_after_shadow_hash" == "$change_after_shadow_report_hash" ]]; then
  pass "change request 记录的 shadow validation 结果与 payload hash 和接口返回一致"
else
  fail "change request shadow validation 结果未对齐: $change_after_shadow_resp"
fi

change_alt_after_shadow_resp="$(api_request GET "/change-requests?proposal_kind=workflow_improvement" "" "local_admin" | select_change_request_by_id "$change_request_alt_id")"
change_alt_after_shadow_status="$(printf '%s' "$change_alt_after_shadow_resp" | extract_json_field "shadow_validation_status" | tr -d '"')"
change_alt_after_shadow_ready="$(printf '%s' "$change_alt_after_shadow_resp" | extract_json_field "shadow_validation_ready_to_apply" | tr -d '"')"
change_alt_after_shadow_match="$(printf '%s' "$change_alt_after_shadow_resp" | extract_json_field "shadow_validation_candidate_match" | tr -d '"')"
if [[ "$change_alt_after_shadow_status" == "required" && "$change_alt_after_shadow_ready" == "false" && "$change_alt_after_shadow_match" == "false" ]]; then
  pass "不同 payload 的第二张 change request 未被错误放行"
else
  fail "不同 payload 的第二张 change request 被错误放行: $change_alt_after_shadow_resp"
fi

apply_alt_gate_resp="$(api_request_with_status POST "/change-requests/${change_request_alt_id}/apply" "" "local_admin")"
apply_alt_gate_status="$(printf '%s' "$apply_alt_gate_resp" | head -n1 | tr -d '\r')"
if [[ "$apply_alt_gate_status" == "409" ]]; then
  pass "第二张 change request 仍被 shadow validation gate 拦截"
else
  fail "第二张 change request 未继续被 gate 拦截: ${apply_alt_gate_resp}"
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
