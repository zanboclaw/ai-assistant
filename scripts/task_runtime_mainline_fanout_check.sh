#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-${ROOT_DIR}/logs}"
API_BASE="${API_BASE:-http://localhost:8000}"
mkdir -p "$LOG_DIR"
source "${ROOT_DIR}/scripts/http_fallback.sh"

TS="$(date +%F_%H%M%S)"
LOG_FILE="${LOG_DIR}/task_runtime_mainline_fanout_check_${TS}.log"

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

section "Create Mainline Fanout Task"
task_resp="$(python3 - <<'PY' | api_request_stdin POST "/tasks" "local_admin"
import json
print(json.dumps({
    "user_input": "执行命令 `sleep 5` 并整理输出"
}, ensure_ascii=False))
PY
)"
task_id="$(printf '%s' "$task_resp" | extract_json_field "id" | tr -d '"')"
if [[ "$task_id" =~ ^[0-9]+$ ]]; then
  pass "成功创建 mainline fanout smoke task #$task_id"
else
  fail "创建 mainline fanout smoke task 失败: $task_resp"
fi

section "Wait Runtime Fanout Visibility"
task_status=""
task_state=""
summary_resp=""
agent_runs_resp=""
runtime_completed_count="0"
for _ in $(seq 1 60); do
  task_state="$(api_request GET "/tasks/${task_id}")"
  task_status="$(printf '%s' "$task_state" | extract_json_field "status" | tr -d '"')"
  summary_resp="$(api_request GET "/tasks/${task_id}/agent-runs/summary")"
  agent_runs_resp="$(api_request GET "/tasks/${task_id}/agent-runs")"
  runtime_fanout="$(printf '%s' "$summary_resp" | extract_json_field "runtime_fanout_active" | tr -d '"')"
  record_origin="$(printf '%s' "$summary_resp" | extract_json_field "record_origin" | tr -d '"')"
  runtime_specialist_count="$(printf '%s' "$agent_runs_resp" | python3 -c 'import json,sys; rows=json.load(sys.stdin); print(sum(1 for row in rows if row.get("role")=="specialist" and row.get("execution_mode")=="task_runtime_worker_v1"))')"
  runtime_completed_count="$(printf '%s' "$agent_runs_resp" | python3 -c 'import json,sys; rows=json.load(sys.stdin); print(sum(1 for row in rows if row.get("role")=="specialist" and row.get("execution_mode")=="task_runtime_worker_v1" and row.get("status")=="completed"))')"
  if [[ ( "$runtime_fanout" == "true" || "$runtime_fanout" == "True" || "$record_origin" == "mainline_runtime" ) && "${runtime_specialist_count}" -ge 2 && "${runtime_completed_count}" -ge 1 ]]; then
    break
  fi
  sleep 1
done

if [[ "$task_status" == "waiting_approval" || "$task_status" == "running" || "$task_status" == "completed" || "$task_status" == "failed" ]]; then
  pass "任务进入可观测状态 status=${task_status}"
else
  fail "任务未进入可观测状态: ${task_state}"
fi

section "Verify Runtime Fanout Summary"
summary_impl="$(printf '%s' "$summary_resp" | extract_json_field "implementation_status" | tr -d '"')"
summary_origin="$(printf '%s' "$summary_resp" | extract_json_field "record_origin" | tr -d '"')"
summary_backend="$(printf '%s' "$summary_resp" | extract_json_field "execution_backend" | tr -d '"')"
summary_control_mode="$(printf '%s' "$summary_resp" | extract_json_field "control_mode" | tr -d '"')"
summary_runtime_fanout="$(printf '%s' "$summary_resp" | extract_json_field "runtime_fanout_active" | tr -d '"')"
summary_latest_eval_source="$(printf '%s' "$summary_resp" | extract_json_field "latest_evaluator_source" | tr -d '"')"
summary_specialist_count="$(printf '%s' "$summary_resp" | extract_json_field "role_counts.specialist" | tr -d '"')"

if [[ "$summary_impl" == "task_runtime_postrun_v1" && "$summary_backend" == "mainline" && "$summary_control_mode" == "observe_only" && ( "$summary_origin" == "mainline_runtime" || "$summary_origin" == "mainline_postrun" ) ]]; then
  pass "task agent summary 已切到 mainline 观测视图"
else
  fail "task agent summary 未返回预期 mainline 视图: ${summary_resp}"
fi

if [[ "$summary_runtime_fanout" == "true" || "$summary_runtime_fanout" == "True" ]]; then
  pass "task agent summary 标记 runtime_fanout_active=true"
else
  fail "task agent summary 未标记 runtime fanout: ${summary_resp}"
fi

if [[ "$summary_specialist_count" =~ ^[0-9]+$ ]] && (( summary_specialist_count >= 2 )); then
  pass "task agent summary 暴露至少 2 个 specialist"
else
  fail "task agent summary 的 specialist 数量异常: ${summary_resp}"
fi

if [[ -z "$summary_latest_eval_source" ]]; then
  pass "runtime 阶段尚未写入 evaluator source，符合预期"
else
  warn "runtime 阶段已出现 evaluator source=${summary_latest_eval_source}"
fi

section "Verify Specialist Runtime Execution"
runtime_specialist_count="$(printf '%s' "$agent_runs_resp" | python3 -c 'import json,sys; rows=json.load(sys.stdin); print(sum(1 for row in rows if row.get("role")=="specialist" and row.get("execution_mode")=="task_runtime_worker_v1"))')"
task_snapshot_count="$(printf '%s' "$agent_runs_resp" | python3 -c 'import json,sys; rows=json.load(sys.stdin); print(sum(1 for row in rows if row.get("role")=="specialist" and ((row.get("execution_request") or {}).get("subtask_type")=="readonly_task_snapshot")))')"
step_digest_count="$(printf '%s' "$agent_runs_resp" | python3 -c 'import json,sys; rows=json.load(sys.stdin); print(sum(1 for row in rows if row.get("role")=="specialist" and ((row.get("execution_request") or {}).get("subtask_type")=="readonly_step_digest")))')"
restricted_probe_count="$(printf '%s' "$agent_runs_resp" | python3 -c 'import json,sys; rows=json.load(sys.stdin); print(sum(1 for row in rows if row.get("role")=="specialist" and ((row.get("execution_request") or {}).get("subtask_type")=="restricted_shell_probe")))')"
manager_run_id="$(printf '%s' "$summary_resp" | extract_json_field "manager.id" | tr -d '"')"

if [[ "$runtime_specialist_count" =~ ^[0-9]+$ ]] && (( runtime_specialist_count >= 2 )); then
  pass "主链 execution-time fanout 生成了至少 2 个 runtime specialist"
else
  fail "runtime specialist 数量不足: ${agent_runs_resp}"
fi

if [[ "$task_snapshot_count" =~ ^[0-9]+$ ]] && (( task_snapshot_count >= 1 )); then
  pass "runtime specialist 包含 readonly_task_snapshot"
else
  fail "runtime specialist 缺少 readonly_task_snapshot: ${agent_runs_resp}"
fi

if [[ "$step_digest_count" =~ ^[0-9]+$ ]] && (( step_digest_count >= 1 )); then
  pass "runtime specialist 包含 readonly_step_digest"
else
  fail "runtime specialist 缺少 readonly_step_digest: ${agent_runs_resp}"
fi

if [[ "$restricted_probe_count" =~ ^[0-9]+$ ]] && (( restricted_probe_count >= 1 )); then
  pass "runtime specialist 包含 restricted_shell_probe"
else
  fail "runtime specialist 缺少 restricted_shell_probe: ${agent_runs_resp}"
fi

if [[ "$runtime_completed_count" =~ ^[0-9]+$ ]] && (( runtime_completed_count >= 1 )); then
  pass "至少 1 个 runtime specialist 已在终态前完成"
else
  fail "终态前未观测到已完成的 runtime specialist: ${agent_runs_resp}"
fi

section "Verify Manager Runtime Rollup"
if [[ "$manager_run_id" =~ ^[0-9]+$ ]]; then
  manager_artifacts_resp="$(api_request GET "/agent-runs/${manager_run_id}/artifacts?limit=20")"
  manager_rollup_count="$(printf '%s' "$manager_artifacts_resp" | python3 -c 'import json,sys; rows=json.load(sys.stdin); print(sum(1 for row in rows if row.get("artifact_type")=="draft" and ((row.get("content") or {}).get("rollup_stage")=="execution_time_fanin")))')"
  if [[ "$manager_rollup_count" =~ ^[0-9]+$ ]] && (( manager_rollup_count >= 1 )); then
    pass "manager 已生成 execution-time fan-in rollup artifact"
  else
    fail "manager 未生成预期 rollup artifact: ${manager_artifacts_resp}"
  fi
else
  fail "未获取到 manager_run_id: ${summary_resp}"
fi

section "Verify Runtime Audit Events"
fanout_audit_resp="$(api_request GET "/audit-logs?event_type=agent.mainline_runtime_fanout&limit=10")"
fanout_audit_count="$(printf '%s' "$fanout_audit_resp" | python3 -c 'import json,sys; rows=json.load(sys.stdin); print(sum(1 for row in rows if int(row.get("task_id") or 0)==int(sys.argv[1])))' "$task_id")"
fanin_audit_resp="$(api_request GET "/audit-logs?event_type=agent.mainline_runtime_fanin&limit=10")"
fanin_audit_count="$(printf '%s' "$fanin_audit_resp" | python3 -c 'import json,sys; rows=json.load(sys.stdin); print(sum(1 for row in rows if int(row.get("task_id") or 0)==int(sys.argv[1])))' "$task_id")"
execute_audit_resp="$(api_request GET "/audit-logs?event_type=agent.mainline_runtime_execute&limit=10")"
execute_audit_count="$(printf '%s' "$execute_audit_resp" | python3 -c 'import json,sys; rows=json.load(sys.stdin); print(sum(1 for row in rows if int(row.get("task_id") or 0)==int(sys.argv[1])))' "$task_id")"

if [[ "$fanout_audit_count" =~ ^[0-9]+$ ]] && (( fanout_audit_count >= 1 )); then
  pass "audit log 记录了 mainline runtime fanout"
else
  fail "audit log 未记录 mainline runtime fanout: ${fanout_audit_resp}"
fi

if [[ "$fanin_audit_count" =~ ^[0-9]+$ ]] && (( fanin_audit_count >= 1 )); then
  pass "audit log 记录了 mainline runtime fan-in"
else
  fail "audit log 未记录 mainline runtime fan-in: ${fanin_audit_resp}"
fi

if [[ "$execute_audit_count" =~ ^[0-9]+$ ]] && (( execute_audit_count >= 1 )); then
  pass "audit log 记录了 runtime specialist 执行"
else
  fail "audit log 未记录 runtime specialist 执行: ${execute_audit_resp}"
fi

section "Approve Pending Task If Needed"
approval_done="false"
if [[ "$task_status" == "waiting_approval" ]]; then
  approvals_resp="$(api_request GET "/tasks/${task_id}/approvals")"
  approval_id="$(printf '%s' "$approvals_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); pending=next((item for item in data if item.get("status")=="pending"), {}); print(pending.get("id") or "")')"
  if [[ "$approval_id" =~ ^[0-9]+$ ]]; then
    approve_resp="$(api_request POST "/approvals/${approval_id}/approve" '{"note":"task runtime mainline fanout smoke approve"}' "local_admin")"
    if echo "$approve_resp" | grep -q '"approval approved"'; then
      pass "已批准审批 approval_id=${approval_id}"
      approval_done="true"
    else
      fail "审批批准异常: ${approve_resp}"
    fi
  else
    fail "未找到待批准 approval: ${approvals_resp}"
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
      approve_resp="$(api_request POST "/approvals/${approval_id}/approve" '{"note":"task runtime mainline fanout smoke approve"}' "local_admin")"
      if echo "$approve_resp" | grep -q '"approval approved"'; then
        pass "等待终态期间已批准审批 approval_id=${approval_id}"
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
  pass "任务最终进入终态 status=${task_status}"
else
  fail "任务未在预期时间内进入终态: ${task_state}"
fi

section "Verify Final Stage 5/6 Summary"
final_impl="$(printf '%s' "$task_state" | extract_json_field "stage5.implementation_status" | tr -d '"')"
final_eval_source="$(printf '%s' "$task_state" | extract_json_field "stage5.latest_evaluator_source" | tr -d '"')"
final_workflow_action="$(printf '%s' "$task_state" | extract_json_field "stage5.latest_workflow_proposal_action" | tr -d '"')"
if [[ "$final_impl" == "task_runtime_postrun_v1" && "$final_eval_source" == "task_runtime_postrun_v1" && -n "$final_workflow_action" ]]; then
  pass "任务终态已收口 Stage 5/6 主链结果"
else
  fail "任务终态缺少预期 Stage 5/6 主链结果: ${task_state}"
fi

section "Done"
log "日志文件: $LOG_FILE"
log "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT} WARN=${WARN_COUNT}"
if (( FAIL_COUNT > 0 )); then
  exit 1
fi
