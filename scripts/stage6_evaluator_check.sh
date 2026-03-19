#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-${ROOT_DIR}/logs}"
API_BASE="${API_BASE:-http://127.0.0.1:8000}"
mkdir -p "$LOG_DIR"

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
curl -sS -X POST "${API_BASE}/init-db" -H "X-Actor-Name: local_admin" >/dev/null
pass "数据库初始化成功"

section "Create And Prepare Task"
task_resp="$(python3 - <<'PY' | curl -sS -X POST "${API_BASE}/tasks" -H "Content-Type: application/json" -H "X-Actor-Name: local_operator" -d @-
import json
print(json.dumps({
    "user_input": "Stage 6 evaluator smoke task"
}, ensure_ascii=False))
PY
)"
task_id="$(printf '%s' "$task_resp" | extract_json_field "id" | tr -d '"')"
if [[ "$task_id" =~ ^[0-9]+$ ]]; then
  pass "成功创建 evaluator smoke task #$task_id"
else
  fail "创建 evaluator smoke task 失败: $task_resp"
fi

bootstrap_resp="$(python3 - <<'PY' | curl -sS -X POST "${API_BASE}/tasks/${task_id}/agent-runs/bootstrap-demo" -H "Content-Type: application/json" -H "X-Actor-Name: local_operator" -d @-
import json
print(json.dumps({
    "objective": "Bootstrap evaluator smoke",
    "specialist_count": 2,
    "include_reviewer": True,
    "note": "stage6 evaluator smoke"
}, ensure_ascii=False))
PY
)"
bootstrap_count="$(printf '%s' "$bootstrap_resp" | extract_json_field "created_agent_run_count" | tr -d '"')"
if [[ "$bootstrap_count" == "4" ]]; then
  pass "bootstrap-demo 创建了 4 个 agent runs"
else
  fail "bootstrap-demo 返回异常: $bootstrap_resp"
fi

execute_resp="$(python3 - <<'PY' | curl -sS -X POST "${API_BASE}/tasks/${task_id}/agent-runs/execute-demo" -H "Content-Type: application/json" -H "X-Actor-Name: local_operator" -d @-
import json
print(json.dumps({
    "note": "stage6 evaluator execute smoke"
}, ensure_ascii=False))
PY
)"
executed_count="$(printf '%s' "$execute_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(len(data.get("executed_specialist_ids") or []))')"
if [[ "$executed_count" == "2" ]]; then
  pass "execute-demo 完成了 2 个 specialist"
else
  fail "execute-demo 返回异常: $execute_resp"
fi

section "Finalize And Record Evaluator"
finalize_resp="$(python3 - <<'PY' | curl -sS -X POST "${API_BASE}/tasks/${task_id}/agent-runs/finalize-demo" -H "Content-Type: application/json" -H "X-Actor-Name: local_operator" -d @-
import json
print(json.dumps({
    "summary": "Finalize evaluator smoke",
    "note": "stage6 evaluator finalize smoke",
    "reviewer_decision": "approved"
}, ensure_ascii=False))
PY
)"
evaluator_run_id="$(printf '%s' "$finalize_resp" | extract_json_field "evaluator_run_id" | tr -d '"')"
if [[ "$evaluator_run_id" =~ ^[0-9]+$ ]]; then
  pass "finalize-demo 返回 evaluator_run_id"
else
  fail "finalize-demo 未返回 evaluator_run_id: $finalize_resp"
fi

section "Verify Evaluator APIs"
latest_eval_resp="$(curl -sS "${API_BASE}/tasks/${task_id}/evaluator-runs/latest")"
latest_eval_decision="$(printf '%s' "$latest_eval_resp" | extract_json_field "decision" | tr -d '"')"
latest_eval_score="$(printf '%s' "$latest_eval_resp" | extract_json_field "score" | tr -d '"')"
latest_eval_source="$(printf '%s' "$latest_eval_resp" | extract_json_field "source" | tr -d '"')"
latest_eval_failure_reason="$(printf '%s' "$latest_eval_resp" | extract_json_field "failure_reason" | tr -d '"')"
latest_eval_failure_stage="$(printf '%s' "$latest_eval_resp" | extract_json_field "failure_stage" | tr -d '"')"
if [[ "$latest_eval_decision" == "approved" && "$latest_eval_score" =~ ^[0-9]+$ && "$latest_eval_source" == "stage5_finalize_demo" && "$latest_eval_failure_reason" == "none" && "$latest_eval_failure_stage" == "none" ]]; then
  pass "latest evaluator 接口返回决策、评分、来源和 failure taxonomy"
else
  fail "latest evaluator 接口返回异常: $latest_eval_resp"
fi

evaluator_list_resp="$(curl -sS "${API_BASE}/evaluator-runs?task_id=${task_id}&limit=5")"
evaluator_list_count="$(printf '%s' "$evaluator_list_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(len(data))')"
if [[ "$evaluator_list_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "evaluator-runs 列表接口可用"
else
  fail "evaluator-runs 列表为空或异常: $evaluator_list_resp"
fi

task_summary_resp="$(curl -sS "${API_BASE}/tasks/${task_id}/agent-runs/summary")"
summary_eval_id="$(printf '%s' "$task_summary_resp" | extract_json_field "latest_evaluator.id" | tr -d '"')"
summary_failure_reason="$(printf '%s' "$task_summary_resp" | extract_json_field "latest_failure_reason" | tr -d '"')"
summary_failure_stage="$(printf '%s' "$task_summary_resp" | extract_json_field "latest_failure_stage" | tr -d '"')"
if [[ "$summary_eval_id" == "$evaluator_run_id" && "$summary_failure_reason" == "none" && "$summary_failure_stage" == "none" ]]; then
  pass "task 级 agent summary 暴露 latest_evaluator 和 failure taxonomy"
else
  fail "task 级 agent summary 未暴露 latest_evaluator: $task_summary_resp"
fi

section "Verify Monitor And Audit"
monitor_resp="$(curl -sS "${API_BASE}/monitor/overview")"
monitor_total_eval="$(printf '%s' "$monitor_resp" | extract_json_field "evaluator_metrics.total_evaluator_runs" | tr -d '"')"
monitor_recent_eval_count="$(printf '%s' "$monitor_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(len(data.get("recent_evaluator_runs") or []))')"
monitor_reason_none="$(printf '%s' "$monitor_resp" | extract_json_field "evaluator_metrics.runs_by_reason.none" | tr -d '"')"
if [[ "$monitor_total_eval" =~ ^[1-9][0-9]*$ && "$monitor_recent_eval_count" =~ ^[1-9][0-9]*$ && "$monitor_reason_none" =~ ^[1-9][0-9]*$ ]]; then
  pass "monitor/overview 返回 evaluator 聚合、recent_evaluator_runs 和 runs_by_reason"
else
  fail "monitor/overview 未返回 evaluator 聚合: $monitor_resp"
fi

audit_resp="$(curl -sS "${API_BASE}/audit-logs?event_type=evaluator.recorded&limit=5")"
audit_match="$(printf '%s' "$audit_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(any(item.get("task_id")=='"$task_id"' for item in data))')"
if [[ "$audit_match" == "True" ]]; then
  pass "audit log 记录了 evaluator.recorded"
else
  fail "audit log 未记录 evaluator.recorded: $audit_resp"
fi

section "Verify Failure Taxonomy On Rejected Path"
failed_task_resp="$(python3 - <<'PY' | curl -sS -X POST "${API_BASE}/tasks" -H "Content-Type: application/json" -H "X-Actor-Name: local_operator" -d @-
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
  failed_task_state="$(curl -sS "${API_BASE}/tasks/${failed_task_id}" || true)"
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

failed_bootstrap_resp="$(python3 - <<'PY' | curl -sS -X POST "${API_BASE}/tasks/${failed_task_id}/agent-runs/bootstrap-demo" -H "Content-Type: application/json" -H "X-Actor-Name: local_operator" -d @-
import json
print(json.dumps({
    "objective": "Bootstrap failed path evaluator smoke",
    "specialist_count": 2,
    "include_reviewer": True,
    "note": "stage6 evaluator failed path"
}, ensure_ascii=False))
PY
)"
failed_bootstrap_count="$(printf '%s' "$failed_bootstrap_resp" | extract_json_field "created_agent_run_count" | tr -d '"')"
if [[ "$failed_bootstrap_count" == "4" ]]; then
  pass "失败路径 bootstrap-demo 创建了 4 个 agent runs"
else
  fail "失败路径 bootstrap-demo 返回异常: $failed_bootstrap_resp"
fi

failed_finalize_resp="$(python3 - <<'PY' | curl -sS -X POST "${API_BASE}/tasks/${failed_task_id}/agent-runs/finalize-demo" -H "Content-Type: application/json" -H "X-Actor-Name: local_operator" -d @-
import json
print(json.dumps({
    "summary": "Finalize failed evaluator smoke",
    "note": "stage6 evaluator failed finalize",
    "reviewer_decision": "auto"
}, ensure_ascii=False))
PY
)"
failed_eval_id="$(printf '%s' "$failed_finalize_resp" | extract_json_field "evaluator_run_id" | tr -d '"')"
failed_eval_decision="$(printf '%s' "$failed_finalize_resp" | extract_json_field "reviewer_decision" | tr -d '"')"
failed_eval_reason="$(printf '%s' "$failed_finalize_resp" | extract_json_field "failure_reason" | tr -d '"')"
failed_eval_stage="$(printf '%s' "$failed_finalize_resp" | extract_json_field "failure_stage" | tr -d '"')"
if [[ "$failed_eval_id" =~ ^[0-9]+$ && "$failed_eval_decision" == "rejected" && "$failed_eval_reason" == "task_failed_step" && "$failed_eval_stage" == "execution" ]]; then
  pass "失败路径 finalize-demo 返回 rejected evaluator taxonomy"
else
  fail "失败路径 finalize-demo taxonomy 异常: $failed_finalize_resp"
fi

section "Done"
log "日志文件: $LOG_FILE"
log "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT} WARN=${WARN_COUNT}"

if (( FAIL_COUNT > 0 )); then
  exit 1
fi
