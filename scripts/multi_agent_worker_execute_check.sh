#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-${ROOT_DIR}/logs}"
API_BASE="${API_BASE:-http://127.0.0.1:8000}"
mkdir -p "$LOG_DIR"

TS="$(date +%F_%H%M%S)"
LOG_FILE="${LOG_DIR}/multi_agent_worker_execute_check_${TS}.log"

PASS_COUNT=0
FAIL_COUNT=0

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
curl -sS -X POST "${API_BASE}/init-db" -H "X-Actor-Name: local_admin" >/dev/null
pass "数据库初始化成功"

section "Create Demo Task"
task_resp="$(python3 - <<'PY' | curl -sS -X POST "${API_BASE}/tasks" -H "Content-Type: application/json" -H "X-Actor-Name: local_operator" -d @-
import json
print(json.dumps({
    "user_input": "Stage 5 worker execute demo task"
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
bootstrap_resp="$(python3 - <<'PY' | curl -sS -X POST "${API_BASE}/tasks/${task_id}/agent-runs/bootstrap-demo" -H "Content-Type: application/json" -H "X-Actor-Name: local_operator" -d @-
import json
print(json.dumps({
    "objective": "Bootstrap worker execute demo",
    "specialist_count": 2,
    "include_reviewer": True,
    "note": "worker bootstrap smoke"
}, ensure_ascii=False))
PY
)"
bootstrap_count="$(printf '%s' "$bootstrap_resp" | extract_json_field "created_agent_run_count" | tr -d '"')"
if [[ "$bootstrap_count" == "4" ]]; then
  pass "bootstrap-demo 创建了 4 个 agent runs"
else
  fail "bootstrap-demo 失败: $bootstrap_resp"
fi

section "Queue Worker Execution"
execute_resp="$(python3 - <<'PY' | curl -sS -X POST "${API_BASE}/tasks/${task_id}/agent-runs/execute-worker-demo" -H "Content-Type: application/json" -H "X-Actor-Name: local_operator" -d @-
import json
print(json.dumps({
    "note": "worker execute smoke"
}, ensure_ascii=False))
PY
)"
queued_specialist_count="$(printf '%s' "$execute_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(len(data.get("queued_specialist_ids") or []))')"
if [[ "$queued_specialist_count" == "2" ]]; then
  pass "execute-worker-demo 排队了 2 个 specialist"
else
  fail "execute-worker-demo 返回异常: $execute_resp"
fi

section "Wait Worker"
worker_ok="False"
for _ in $(seq 1 20); do
  agent_runs_resp="$(curl -sS "${API_BASE}/tasks/${task_id}/agent-runs")"
  completed_specialists="$(printf '%s' "$agent_runs_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(sum(1 for item in data if item.get("role")=="specialist" and item.get("status")=="completed"))')"
  if [[ "$completed_specialists" == "2" ]]; then
    worker_ok="True"
    break
  fi
  sleep 1
done

if [[ "$worker_ok" == "True" ]]; then
  pass "worker 完成了 2 个 specialist agent runs"
else
  fail "worker 未在预期时间内完成 specialist agent runs"
fi

section "Verify Worker Outputs"
agent_runs_resp="$(curl -sS "${API_BASE}/tasks/${task_id}/agent-runs")"
first_specialist_id="$(printf '%s' "$agent_runs_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); specialists=[item for item in data if item.get("role")=="specialist"]; print(specialists[0]["id"] if specialists else "")')"
first_specialist_mode="$(printf '%s' "$agent_runs_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); specialists=[item for item in data if item.get("role")=="specialist"]; print(specialists[0].get("execution_mode") if specialists else "")')"
if [[ "$first_specialist_id" =~ ^[0-9]+$ && "$first_specialist_mode" == "worker_readonly_v1" ]]; then
  pass "specialist agent run 暴露 execution_mode"
else
  fail "specialist agent run 缺少 execution_mode: $agent_runs_resp"
fi

artifacts_resp="$(curl -sS "${API_BASE}/agent-runs/${first_specialist_id}/artifacts")"
worker_draft_present="$(printf '%s' "$artifacts_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(any(item.get("artifact_type")=="draft" and ((item.get("content") or {}).get("summary")=="worker executed readonly specialist subtask") for item in data))')"
if [[ "$worker_draft_present" == "True" ]]; then
  pass "worker 生成了 specialist draft artifact"
else
  fail "worker 未生成预期 draft artifact: $artifacts_resp"
fi

audit_resp="$(curl -sS "${API_BASE}/audit-logs?event_type=agent.worker_execute_demo&limit=5")"
audit_match="$(printf '%s' "$audit_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(any(item.get("task_id")=='"$task_id"' for item in data))')"
if [[ "$audit_match" == "True" ]]; then
  pass "audit log 记录了 agent.worker_execute_demo"
else
  fail "audit log 未记录 agent.worker_execute_demo: $audit_resp"
fi

section "Done"
log "日志文件: $LOG_FILE"
log "PASS=$PASS_COUNT FAIL=$FAIL_COUNT"
if [[ "$FAIL_COUNT" -gt 0 ]]; then
  exit 1
fi
