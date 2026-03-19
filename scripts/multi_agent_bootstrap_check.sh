#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-${ROOT_DIR}/logs}"
mkdir -p "$LOG_DIR"

TS="$(date +%F_%H%M%S)"
LOG_FILE="${LOG_DIR}/multi_agent_bootstrap_check_${TS}.log"

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
curl -sS -X POST "http://localhost:8000/init-db" -H "X-Actor-Name: local_admin" >/dev/null
pass "数据库初始化成功"

section "Create Demo Task"
task_resp="$(python3 - <<'PY' | curl -sS -X POST "http://localhost:8000/tasks" -H "Content-Type: application/json" -H "X-Actor-Name: local_operator" -d @-
import json
print(json.dumps({
    "user_input": "Stage 5 bootstrap demo task: summarize the current repo status into a manager/specialist/reviewer skeleton"
}, ensure_ascii=False))
PY
)"
task_id="$(printf '%s' "$task_resp" | extract_json_field "id" | tr -d '"')"
if [[ "$task_id" =~ ^[0-9]+$ ]]; then
  pass "成功创建 demo task #$task_id"
else
  fail "创建 demo task 失败: $task_resp"
fi

section "Bootstrap Demo"
bootstrap_resp="$(python3 - <<'PY' | curl -sS -X POST "http://localhost:8000/tasks/${task_id}/agent-runs/bootstrap-demo" -H "Content-Type: application/json" -H "X-Actor-Name: local_operator" -d @-
import json
print(json.dumps({
    "objective": "Bootstrap a minimal manager-only orchestration demo",
    "specialist_count": 2,
    "include_reviewer": True,
    "note": "bootstrap smoke"
}, ensure_ascii=False))
PY
)"
created_agent_run_count="$(printf '%s' "$bootstrap_resp" | extract_json_field "created_agent_run_count" | tr -d '"')"
if [[ "$created_agent_run_count" == "4" ]]; then
  pass "bootstrap-demo 创建了 4 个 agent runs"
else
  fail "bootstrap-demo agent run 数量不符合预期: $bootstrap_resp"
fi

section "Verify Task Agent Runs"
agent_runs_resp="$(curl -sS "http://localhost:8000/tasks/${task_id}/agent-runs")"
agent_summary_resp="$(curl -sS "http://localhost:8000/tasks/${task_id}/agent-runs/summary")"
agent_run_count="$(printf '%s' "$agent_runs_resp" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
if [[ "$agent_run_count" == "4" ]]; then
  pass "task 级 agent-runs 列表返回 4 条记录"
else
  fail "task 级 agent-runs 数量不符合预期: $agent_runs_resp"
fi

summary_recommended_action="$(printf '%s' "$agent_summary_resp" | extract_json_field "recommended_action" | tr -d '"')"
summary_awaiting_role="$(printf '%s' "$agent_summary_resp" | extract_json_field "awaiting_role" | tr -d '"')"
if [[ "$summary_recommended_action" == "execute" ]]; then
  pass "task 级 agent summary 返回 execute 推荐动作"
else
  fail "task 级 agent summary 推荐动作异常: $agent_summary_resp"
fi
if [[ "$summary_awaiting_role" == "specialist" ]]; then
  pass "task 级 agent summary 返回 specialist awaiting_role"
else
  fail "task 级 agent summary awaiting_role 异常: $agent_summary_resp"
fi

tasks_with_stage5_resp="$(curl -sS "http://localhost:8000/tasks?include_stage5_summary=true")"
stage5_summary_present="$(printf '%s' "$tasks_with_stage5_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); target=next((item for item in data if item.get("id")=='"$task_id"'), {}); print(bool((target.get("stage5") or {}).get("recommended_action")))')"
if [[ "$stage5_summary_present" == "True" ]]; then
  pass "tasks 列表支持返回 task 级 stage5 summary"
else
  fail "tasks 列表未返回 task 级 stage5 summary: $tasks_with_stage5_resp"
fi

manager_count="$(printf '%s' "$agent_runs_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(sum(1 for item in data if item.get("role")=="manager"))')"
specialist_count="$(printf '%s' "$agent_runs_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(sum(1 for item in data if item.get("role")=="specialist"))')"
reviewer_count="$(printf '%s' "$agent_runs_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(sum(1 for item in data if item.get("role")=="reviewer"))')"
specialist_has_execution_request="$(printf '%s' "$agent_runs_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); specialists=[item for item in data if item.get("role")=="specialist"]; print(all(bool(item.get("execution_request")) for item in specialists) if specialists else False)')"
if [[ "$manager_count" == "1" && "$specialist_count" == "2" && "$reviewer_count" == "1" ]]; then
  pass "agent 角色分布正确"
else
  fail "agent 角色分布不符合预期: $agent_runs_resp"
fi
if [[ "$specialist_has_execution_request" == "True" ]]; then
  pass "specialist agent_runs 持久化了 execution_request"
else
  fail "specialist agent_runs 未持久化 execution_request: $agent_runs_resp"
fi

section "Verify Messages And Artifacts"
first_agent_id="$(printf '%s' "$agent_runs_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); specialists=[item for item in data if item.get("role")=="specialist"]; print(specialists[0]["id"] if specialists else "")')"
if [[ ! "$first_agent_id" =~ ^[0-9]+$ ]]; then
  fail "未找到 specialist agent id: $agent_runs_resp"
else
  messages_resp="$(curl -sS "http://localhost:8000/agent-runs/${first_agent_id}/messages")"
  artifacts_resp="$(curl -sS "http://localhost:8000/agent-runs/${first_agent_id}/artifacts")"
  messages_count="$(printf '%s' "$messages_resp" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
  artifacts_count="$(printf '%s' "$artifacts_resp" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
  brief_has_execution_request="$(printf '%s' "$artifacts_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); brief=next((item for item in data if item.get("artifact_type")=="brief"), {}); content=brief.get("content") or {}; print(bool(content.get("execution_request")))')"
  if [[ "$messages_count" =~ ^[1-9][0-9]*$ ]]; then
    pass "specialist agent 能读取到至少 1 条消息"
  else
    fail "specialist agent 未读取到消息: $messages_resp"
  fi
  if [[ "$artifacts_count" =~ ^[1-9][0-9]*$ ]]; then
    pass "specialist agent 能读取到至少 1 条 artifact"
  else
    fail "specialist agent 未读取到 artifact: $artifacts_resp"
  fi
  if [[ "$brief_has_execution_request" == "True" ]]; then
    pass "specialist brief artifact 暴露 execution_request"
  else
    fail "specialist brief artifact 缺少 execution_request: $artifacts_resp"
  fi
fi

section "Verify Audit Trail"
audit_resp="$(curl -sS "http://localhost:8000/audit-logs?event_type=agent.bootstrap_demo&limit=5")"
audit_match="$(printf '%s' "$audit_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(any(item.get("task_id")=='"$task_id"' for item in data))')"
if [[ "$audit_match" == "True" ]]; then
  pass "audit log 记录了 agent.bootstrap_demo"
else
  fail "audit log 未记录 agent.bootstrap_demo: $audit_resp"
fi

section "Execute Demo"
execute_resp="$(python3 - <<'PY' | curl -sS -X POST "http://localhost:8000/tasks/${task_id}/agent-runs/execute-demo" -H "Content-Type: application/json" -H "X-Actor-Name: local_operator" -d @-
import json
print(json.dumps({
    "note": "execute smoke"
}, ensure_ascii=False))
PY
)"
executed_specialist_count="$(printf '%s' "$execute_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(len(data.get("executed_specialist_ids") or []))')"
if [[ "$executed_specialist_count" == "2" ]]; then
  pass "execute-demo 执行了 2 个 specialist"
else
  fail "execute-demo specialist 数量不符合预期: $execute_resp"
fi

agent_runs_after_execute="$(curl -sS "http://localhost:8000/tasks/${task_id}/agent-runs")"
completed_specialists_after_execute="$(printf '%s' "$agent_runs_after_execute" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(sum(1 for item in data if item.get("role")=="specialist" and item.get("status")=="completed"))')"
if [[ "$completed_specialists_after_execute" == "2" ]]; then
  pass "execute-demo 后 2 个 specialist 都为 completed"
else
  fail "execute-demo 后 specialist 状态不符合预期: $agent_runs_after_execute"
fi

specialist_artifacts_after_execute="$(curl -sS "http://localhost:8000/agent-runs/${first_agent_id}/artifacts")"
specialist_execution_mode="$(printf '%s' "$specialist_artifacts_after_execute" | python3 -c 'import json,sys; data=json.load(sys.stdin); draft=next((item for item in data if item.get("artifact_type")=="draft"), {}); content=draft.get("content") or {}; output=content.get("output") or {}; subtask=output.get("subtask") or {}; print(subtask.get("execution_mode") or "")')"
specialist_subtask_type="$(printf '%s' "$specialist_artifacts_after_execute" | python3 -c 'import json,sys; data=json.load(sys.stdin); draft=next((item for item in data if item.get("artifact_type")=="draft"), {}); content=draft.get("content") or {}; output=content.get("output") or {}; subtask=output.get("subtask") or {}; print(subtask.get("type") or "")')"
draft_has_request_snapshot="$(printf '%s' "$specialist_artifacts_after_execute" | python3 -c 'import json,sys; data=json.load(sys.stdin); draft=next((item for item in data if item.get("artifact_type")=="draft"), {}); content=draft.get("content") or {}; output=content.get("output") or {}; result=output.get("execution_result") or {}; print(bool(result.get("request_snapshot")))')"
if [[ "$specialist_execution_mode" == "api_readonly_subtask_v1" && "$specialist_subtask_type" == "readonly_step_digest" && "$draft_has_request_snapshot" == "True" ]]; then
  pass "execute-demo draft artifact 记录了只读 specialist 子任务元数据"
else
  fail "execute-demo draft artifact 未记录预期子任务元数据: $specialist_artifacts_after_execute"
fi

execute_audit_resp="$(curl -sS "http://localhost:8000/audit-logs?event_type=agent.execute_demo&limit=5")"
execute_audit_match="$(printf '%s' "$execute_audit_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(any(item.get("task_id")=='"$task_id"' for item in data))')"
if [[ "$execute_audit_match" == "True" ]]; then
  pass "audit log 记录了 agent.execute_demo"
else
  fail "audit log 未记录 agent.execute_demo: $execute_audit_resp"
fi

section "Finalize Demo"
finalize_resp="$(python3 - <<'PY' | curl -sS -X POST "http://localhost:8000/tasks/${task_id}/agent-runs/finalize-demo" -H "Content-Type: application/json" -H "X-Actor-Name: local_operator" -d @-
import json
print(json.dumps({
    "summary": "Finalize manager demo for smoke",
    "note": "finalize smoke",
    "reviewer_decision": "approved"
}, ensure_ascii=False))
PY
)"
final_artifact_id="$(printf '%s' "$finalize_resp" | extract_json_field "final_artifact_id" | tr -d '"')"
quality_score_approved="$(printf '%s' "$finalize_resp" | extract_json_field "quality_score" | tr -d '"')"
reviewer_decision_approved="$(printf '%s' "$finalize_resp" | extract_json_field "reviewer_decision" | tr -d '"')"
decision_source_approved="$(printf '%s' "$finalize_resp" | extract_json_field "decision_source" | tr -d '"')"
if [[ "$final_artifact_id" =~ ^[0-9]+$ ]]; then
  pass "finalize-demo 创建了 final artifact"
else
  fail "finalize-demo 未返回 final artifact: $finalize_resp"
fi
if [[ "$quality_score_approved" =~ ^[0-9]+$ ]]; then
  pass "approved 分支返回 quality_score"
else
  fail "approved 分支未返回 quality_score: $finalize_resp"
fi
if [[ "$reviewer_decision_approved" == "approved" && "$decision_source_approved" == "manual" ]]; then
  pass "approved 分支支持显式 reviewer 决策"
else
  fail "approved 分支 reviewer 决策异常: $finalize_resp"
fi

agent_runs_after_finalize="$(curl -sS "http://localhost:8000/tasks/${task_id}/agent-runs")"
completed_count="$(printf '%s' "$agent_runs_after_finalize" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(sum(1 for item in data if item.get("status")=="completed"))')"
if [[ "$completed_count" == "4" ]]; then
  pass "finalize-demo 后 4 个 agent runs 都为 completed"
else
  fail "finalize-demo 后 agent status 不符合预期: $agent_runs_after_finalize"
fi

finalize_audit_resp="$(curl -sS "http://localhost:8000/audit-logs?event_type=agent.finalize_demo&limit=5")"
finalize_audit_match="$(printf '%s' "$finalize_audit_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(any(item.get("task_id")=='"$task_id"' for item in data))')"
if [[ "$finalize_audit_match" == "True" ]]; then
  pass "audit log 记录了 agent.finalize_demo"
else
  fail "audit log 未记录 agent.finalize_demo: $finalize_audit_resp"
fi

monitor_resp="$(curl -sS "http://localhost:8000/monitor/overview")"
monitor_stage5_execute="$(printf '%s' "$monitor_resp" | extract_json_field "agent_metrics.tasks_requiring_execute" | tr -d '"')"
monitor_stage5_finalize="$(printf '%s' "$monitor_resp" | extract_json_field "agent_metrics.tasks_requiring_finalize" | tr -d '"')"
if [[ "$monitor_stage5_execute" =~ ^[0-9]+$ && "$monitor_stage5_finalize" =~ ^[0-9]+$ ]]; then
  pass "monitor/overview 返回 Stage 5 聚合计数"
else
  fail "monitor/overview 未返回 Stage 5 聚合计数: $monitor_resp"
fi

section "Rework Branch"
task_rework_resp="$(python3 - <<'PY' | curl -sS -X POST "http://localhost:8000/tasks" -H "Content-Type: application/json" -H "X-Actor-Name: local_operator" -d @-
import json
print(json.dumps({
    "user_input": "Stage 5 rework branch demo task"
}, ensure_ascii=False))
PY
)"
task_rework_id="$(printf '%s' "$task_rework_resp" | extract_json_field "id" | tr -d '"')"
bootstrap_rework_resp="$(python3 - <<'PY' | curl -sS -X POST "http://localhost:8000/tasks/${task_rework_id}/agent-runs/bootstrap-demo" -H "Content-Type: application/json" -H "X-Actor-Name: local_operator" -d @-
import json
print(json.dumps({
    "objective": "Bootstrap rework branch",
    "specialist_count": 2,
    "include_reviewer": True,
    "note": "bootstrap rework smoke"
}, ensure_ascii=False))
PY
)"
bootstrap_rework_count="$(printf '%s' "$bootstrap_rework_resp" | extract_json_field "created_agent_run_count" | tr -d '"')"
if [[ "$bootstrap_rework_count" == "4" ]]; then
  pass "rework 分支 bootstrap-demo 创建了 4 个 agent runs"
else
  fail "rework 分支 bootstrap-demo 失败: $bootstrap_rework_resp"
fi

finalize_rework_resp="$(python3 - <<'PY' | curl -sS -X POST "http://localhost:8000/tasks/${task_rework_id}/agent-runs/finalize-demo" -H "Content-Type: application/json" -H "X-Actor-Name: local_operator" -d @-
import json
print(json.dumps({
    "summary": "Finalize manager rework demo",
    "note": "finalize rework smoke",
    "reviewer_decision": "rework_required"
}, ensure_ascii=False))
PY
)"
manager_status_rework="$(printf '%s' "$finalize_rework_resp" | extract_json_field "manager_status" | tr -d '"')"
reviewer_decision_rework="$(printf '%s' "$finalize_rework_resp" | extract_json_field "reviewer_decision" | tr -d '"')"
failure_reason_rework="$(printf '%s' "$finalize_rework_resp" | extract_json_field "failure_reason" | tr -d '"')"
failure_stage_rework="$(printf '%s' "$finalize_rework_resp" | extract_json_field "failure_stage" | tr -d '"')"
if [[ "$manager_status_rework" == "blocked" && "$reviewer_decision_rework" == "rework_required" ]]; then
  pass "rework 分支 finalize-demo 返回 blocked manager 状态"
else
  fail "rework 分支 finalize-demo 返回异常: $finalize_rework_resp"
fi
if [[ "$failure_reason_rework" == "reviewer_requested_rework" && "$failure_stage_rework" == "review" ]]; then
  pass "rework 分支返回 evaluator failure taxonomy"
else
  fail "rework 分支 evaluator failure taxonomy 异常: $finalize_rework_resp"
fi
next_strategy_rework="$(printf '%s' "$finalize_rework_resp" | extract_json_field "next_strategy" | tr -d '"')"
quality_score_rework="$(printf '%s' "$finalize_rework_resp" | extract_json_field "quality_score" | tr -d '"')"
if [[ "$next_strategy_rework" == "retry_specialists" ]]; then
  pass "rework 分支返回 retry_specialists 策略"
else
  fail "rework 分支未返回 retry_specialists 策略: $finalize_rework_resp"
fi
if [[ "$quality_score_rework" =~ ^[0-9]+$ ]]; then
  pass "rework 分支返回 quality_score"
else
  fail "rework 分支未返回 quality_score: $finalize_rework_resp"
fi

execute_rework_resp="$(python3 - <<'PY' | curl -sS -X POST "http://localhost:8000/tasks/${task_rework_id}/agent-runs/execute-demo" -H "Content-Type: application/json" -H "X-Actor-Name: local_operator" -d @-
import json
print(json.dumps({
    "note": "execute rework smoke",
    "force_rerun": True
}, ensure_ascii=False))
PY
)"
retried_specialist_count="$(printf '%s' "$execute_rework_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(len(data.get("retried_specialist_ids") or []))')"
if [[ "$retried_specialist_count" == "2" ]]; then
  pass "rework 分支 execute-demo 支持强制重跑 2 个 specialist"
else
  fail "rework 分支 execute-demo 强制重跑异常: $execute_rework_resp"
fi

finalize_rework_retry_resp="$(python3 - <<'PY' | curl -sS -X POST "http://localhost:8000/tasks/${task_rework_id}/agent-runs/finalize-demo" -H "Content-Type: application/json" -H "X-Actor-Name: local_operator" -d @-
import json
print(json.dumps({
    "summary": "Finalize manager rework retry demo",
    "note": "finalize rework retry smoke",
    "reviewer_decision": "approved",
    "allow_retry": True
}, ensure_ascii=False))
PY
)"
manager_status_rework_retry="$(printf '%s' "$finalize_rework_retry_resp" | extract_json_field "manager_status" | tr -d '"')"
final_artifact_version_rework_retry="$(printf '%s' "$finalize_rework_retry_resp" | extract_json_field "final_artifact_version" | tr -d '"')"
if [[ "$manager_status_rework_retry" == "completed" && "$final_artifact_version_rework_retry" == "2" ]]; then
  pass "rework 分支 allow_retry 后成功生成 version=2 的 final artifact"
else
  fail "rework 分支 allow_retry 返回异常: $finalize_rework_retry_resp"
fi

agent_runs_rework="$(curl -sS "http://localhost:8000/tasks/${task_rework_id}/agent-runs")"
agent_summary_rework="$(curl -sS "http://localhost:8000/tasks/${task_rework_id}/agent-runs/summary")"
blocked_count_rework="$(printf '%s' "$agent_runs_rework" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(sum(1 for item in data if item.get("status")=="blocked"))')"
completed_count_rework="$(printf '%s' "$agent_runs_rework" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(sum(1 for item in data if item.get("status")=="completed"))')"
if [[ "$blocked_count_rework" == "0" && "$completed_count_rework" == "4" ]]; then
  pass "rework 分支在重跑并重汇总后 4 个 agent runs 都回到 completed"
else
  fail "rework 分支 agent status 不符合预期: $agent_runs_rework"
fi

summary_rework_action="$(printf '%s' "$agent_summary_rework" | extract_json_field "recommended_action" | tr -d '"')"
summary_rework_final_version="$(printf '%s' "$agent_summary_rework" | extract_json_field "latest_final_artifact.version" | tr -d '"')"
summary_rework_awaiting_role="$(printf '%s' "$agent_summary_rework" | extract_json_field "awaiting_role" | tr -d '"')"
if [[ "$summary_rework_action" == "none" && "$summary_rework_final_version" == "2" && "$summary_rework_awaiting_role" == "" ]]; then
  pass "rework 重试后 task 级 agent summary 反映 final v2 已稳定"
else
  fail "rework 重试后 task 级 agent summary 异常: $agent_summary_rework"
fi

finalize_rework_audit_resp="$(curl -sS "http://localhost:8000/audit-logs?event_type=agent.finalize_demo&limit=10")"
finalize_rework_audit_match="$(printf '%s' "$finalize_rework_audit_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(any(item.get("task_id")=='"$task_rework_id"' and (item.get("details") or {}).get("reviewer_decision")=="rework_required" for item in data))')"
if [[ "$finalize_rework_audit_match" == "True" ]]; then
  pass "audit log 记录了 rework_required 分支"
else
  fail "audit log 未记录 rework_required 分支: $finalize_rework_audit_resp"
fi

section "Rejected Branch"
task_rejected_resp="$(python3 - <<'PY' | curl -sS -X POST "http://localhost:8000/tasks" -H "Content-Type: application/json" -H "X-Actor-Name: local_operator" -d @-
import json
print(json.dumps({
    "user_input": "Stage 5 rejected branch demo task"
}, ensure_ascii=False))
PY
)"
task_rejected_id="$(printf '%s' "$task_rejected_resp" | extract_json_field "id" | tr -d '"')"
bootstrap_rejected_resp="$(python3 - <<'PY' | curl -sS -X POST "http://localhost:8000/tasks/${task_rejected_id}/agent-runs/bootstrap-demo" -H "Content-Type: application/json" -H "X-Actor-Name: local_operator" -d @-
import json
print(json.dumps({
    "objective": "Bootstrap rejected branch",
    "specialist_count": 2,
    "include_reviewer": True,
    "note": "bootstrap rejected smoke"
}, ensure_ascii=False))
PY
)"
bootstrap_rejected_count="$(printf '%s' "$bootstrap_rejected_resp" | extract_json_field "created_agent_run_count" | tr -d '"')"
if [[ "$bootstrap_rejected_count" == "4" ]]; then
  pass "rejected 分支 bootstrap-demo 创建了 4 个 agent runs"
else
  fail "rejected 分支 bootstrap-demo 失败: $bootstrap_rejected_resp"
fi

finalize_rejected_resp="$(python3 - <<'PY' | curl -sS -X POST "http://localhost:8000/tasks/${task_rejected_id}/agent-runs/finalize-demo" -H "Content-Type: application/json" -H "X-Actor-Name: local_operator" -d @-
import json
print(json.dumps({
    "summary": "Finalize manager rejected demo",
    "note": "finalize rejected smoke",
    "reviewer_decision": "rejected"
}, ensure_ascii=False))
PY
)"
manager_status_rejected="$(printf '%s' "$finalize_rejected_resp" | extract_json_field "manager_status" | tr -d '"')"
reviewer_decision_rejected="$(printf '%s' "$finalize_rejected_resp" | extract_json_field "reviewer_decision" | tr -d '"')"
next_strategy_rejected="$(printf '%s' "$finalize_rejected_resp" | extract_json_field "next_strategy" | tr -d '"')"
quality_score_rejected="$(printf '%s' "$finalize_rejected_resp" | extract_json_field "quality_score" | tr -d '"')"
failure_reason_rejected="$(printf '%s' "$finalize_rejected_resp" | extract_json_field "failure_reason" | tr -d '"')"
failure_stage_rejected="$(printf '%s' "$finalize_rejected_resp" | extract_json_field "failure_stage" | tr -d '"')"
if [[ "$manager_status_rejected" == "failed" && "$reviewer_decision_rejected" == "rejected" && "$next_strategy_rejected" == "escalate_to_operator" ]]; then
  pass "rejected 分支 finalize-demo 返回 failed manager 状态和升级策略"
else
  fail "rejected 分支 finalize-demo 返回异常: $finalize_rejected_resp"
fi
if [[ "$failure_reason_rejected" == "reviewer_rejected" && "$failure_stage_rejected" == "review" ]]; then
  pass "rejected 分支返回 evaluator failure taxonomy"
else
  fail "rejected 分支 evaluator failure taxonomy 异常: $finalize_rejected_resp"
fi
if [[ "$quality_score_rejected" =~ ^[0-9]+$ ]]; then
  pass "rejected 分支返回 quality_score"
else
  fail "rejected 分支未返回 quality_score: $finalize_rejected_resp"
fi

agent_runs_rejected="$(curl -sS "http://localhost:8000/tasks/${task_rejected_id}/agent-runs")"
failed_count_rejected="$(printf '%s' "$agent_runs_rejected" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(sum(1 for item in data if item.get("status")=="failed"))')"
if [[ "$failed_count_rejected" == "1" ]]; then
  pass "rejected 分支存在 1 个 failed agent run"
else
  fail "rejected 分支 agent status 不符合预期: $agent_runs_rejected"
fi

manager_agent_id_rejected="$(printf '%s' "$agent_runs_rejected" | python3 -c 'import json,sys; data=json.load(sys.stdin); managers=[item for item in data if item.get("role")=="manager"]; print(managers[0]["id"] if managers else "")')"
manager_messages_rejected="$(curl -sS "http://localhost:8000/agent-runs/${manager_agent_id_rejected}/messages")"
escalation_count_rejected="$(printf '%s' "$manager_messages_rejected" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(sum(1 for item in data if item.get("message_type")=="escalation" and item.get("recipient_role")=="operator"))')"
if [[ "$escalation_count_rejected" =~ ^[1-9][0-9]*$ ]]; then
  pass "rejected 分支产生了 manager->operator escalation 消息"
else
  fail "rejected 分支未产生 escalation 消息: $manager_messages_rejected"
fi

finalize_rejected_audit_resp="$(curl -sS "http://localhost:8000/audit-logs?event_type=agent.finalize_demo&limit=15")"
finalize_rejected_audit_match="$(printf '%s' "$finalize_rejected_audit_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(any(item.get("task_id")=='"$task_rejected_id"' and (item.get("details") or {}).get("reviewer_decision")=="rejected" and (item.get("details") or {}).get("next_strategy")=="escalate_to_operator" for item in data))')"
if [[ "$finalize_rejected_audit_match" == "True" ]]; then
  pass "audit log 记录了 rejected -> escalate_to_operator 分支"
else
  fail "audit log 未记录 rejected 分支: $finalize_rejected_audit_resp"
fi

section "Done"
log "日志文件: $LOG_FILE"
log "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT} WARN=${WARN_COUNT}"

if (( FAIL_COUNT > 0 )); then
  exit 1
fi
