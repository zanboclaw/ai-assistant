#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-${ROOT_DIR}/logs}"
API_BASE="${API_BASE:-http://127.0.0.1:8000}"
WORKSPACE_DIR="${ROOT_DIR}/data/workspace"
mkdir -p "$LOG_DIR" "$WORKSPACE_DIR"

TS="$(date +%F_%H%M%S)"
LOG_FILE="${LOG_DIR}/multi_agent_source_snapshot_check_${TS}.log"

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

section "Prepare Source"
SOURCE_HOST_PATH="${WORKSPACE_DIR}/stage5_source_snapshot_smoke.json"
cat >"$SOURCE_HOST_PATH" <<'EOF'
{
  "meta": {
    "title": "snapshot smoke",
    "owner": "stage5"
  },
  "items": ["alpha", "beta", "gamma"]
}
EOF
pass "准备了 source snapshot 测试文件"

section "Init DB"
curl -sS -X POST "${API_BASE}/init-db" -H "X-Actor-Name: local_admin" >/dev/null
pass "数据库初始化成功"

section "Create Demo Task"
task_resp="$(python3 - <<'PY' | curl -sS -X POST "${API_BASE}/tasks" -H "Content-Type: application/json" -H "X-Actor-Name: local_admin" -d @-
import json
print(json.dumps({
    "user_input": "Stage 5 source snapshot smoke task"
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
bootstrap_resp="$(python3 - <<'PY' | curl -sS -X POST "${API_BASE}/tasks/${task_id}/agent-runs/bootstrap-demo" -H "Content-Type: application/json" -H "X-Actor-Name: local_admin" -d @-
import json
print(json.dumps({
    "objective": "Bootstrap source snapshot demo",
    "specialist_count": 1,
    "include_reviewer": False,
    "note": "source snapshot smoke"
}, ensure_ascii=False))
PY
)"
bootstrap_count="$(printf '%s' "$bootstrap_resp" | extract_json_field "created_agent_run_count" | tr -d '"')"
if [[ "$bootstrap_count" == "2" ]]; then
  pass "bootstrap-demo 创建了 2 个 agent runs"
else
  fail "bootstrap-demo 返回异常: $bootstrap_resp"
fi

section "Queue Worker Source Snapshot"
execute_resp="$(python3 - <<'PY' | curl -sS -X POST "${API_BASE}/tasks/${task_id}/agent-runs/execute-worker-demo" -H "Content-Type: application/json" -H "X-Actor-Name: local_admin" -d @-
import json
print(json.dumps({
    "note": "source snapshot smoke",
    "subtask_type": "readonly_source_snapshot",
    "source_kind": "json_file",
    "source_path": "/workspace/stage5_source_snapshot_smoke.json",
    "source_json_path": "meta.title"
}, ensure_ascii=False))
PY
)"
queued_specialist_count="$(printf '%s' "$execute_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(len(data.get("queued_specialist_ids") or []))')"
queued_subtask_type="$(printf '%s' "$execute_resp" | extract_json_field "subtask_type" | tr -d '"')"
if [[ "$queued_specialist_count" == "1" && "$queued_subtask_type" == "readonly_source_snapshot" ]]; then
  pass "execute-worker-demo 排队了 1 个 source snapshot specialist"
else
  fail "execute-worker-demo 返回异常: $execute_resp"
fi

section "Wait Worker"
worker_ok="False"
for _ in $(seq 1 30); do
  agent_runs_resp="$(curl -sS "${API_BASE}/tasks/${task_id}/agent-runs")"
  completed_specialists="$(printf '%s' "$agent_runs_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(sum(1 for item in data if item.get("role")=="specialist" and item.get("status")=="completed"))')"
  if [[ "$completed_specialists" == "1" ]]; then
    worker_ok="True"
    break
  fi
  sleep 1
done
if [[ "$worker_ok" == "True" ]]; then
  pass "worker 完成了 source snapshot specialist"
else
  fail "worker 未在预期时间内完成 source snapshot specialist"
fi

section "Verify Draft Artifact"
agent_runs_resp="$(curl -sS "${API_BASE}/tasks/${task_id}/agent-runs")"
specialist_id="$(printf '%s' "$agent_runs_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); specialists=[item for item in data if item.get("role")=="specialist"]; print(specialists[0]["id"] if specialists else "")')"
artifacts_resp="$(curl -sS "${API_BASE}/agent-runs/${specialist_id}/artifacts")"
subtask_type="$(printf '%s' "$artifacts_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); draft=next((item for item in data if item.get("artifact_type")=="draft"), {}); output=(draft.get("content") or {}).get("output") or {}; subtask=output.get("subtask") or {}; print(subtask.get("type") or "")')"
selected_value="$(printf '%s' "$artifacts_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); draft=next((item for item in data if item.get("artifact_type")=="draft"), {}); output=(draft.get("content") or {}).get("output") or {}; result=output.get("execution_result") or {}; source=result.get("source") or {}; print(source.get("selected_value") or "")')"
source_kind="$(printf '%s' "$artifacts_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); draft=next((item for item in data if item.get("artifact_type")=="draft"), {}); output=(draft.get("content") or {}).get("output") or {}; result=output.get("execution_result") or {}; source=result.get("source") or {}; print(source.get("kind") or "")')"
source_path="$(printf '%s' "$artifacts_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); draft=next((item for item in data if item.get("artifact_type")=="draft"), {}); output=(draft.get("content") or {}).get("output") or {}; result=output.get("execution_result") or {}; source=result.get("source") or {}; print(source.get("path") or "")')"
if [[ "$subtask_type" == "readonly_source_snapshot" && "$selected_value" == "snapshot smoke" && "$source_kind" == "json_file" && "$source_path" == "/workspace/stage5_source_snapshot_smoke.json" ]]; then
  pass "draft artifact 记录了 readonly_source_snapshot 的真实 source 结果"
else
  fail "draft artifact source snapshot 内容异常: $artifacts_resp"
fi

section "Verify Audit"
audit_resp="$(curl -sS "${API_BASE}/audit-logs?event_type=agent.worker_execute_demo&limit=5")"
audit_match="$(printf '%s' "$audit_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(any(item.get("task_id")=='"$task_id"' for item in data))')"
if [[ "$audit_match" == "True" ]]; then
  pass "audit log 记录了 source snapshot worker 执行"
else
  fail "audit log 未记录 source snapshot worker 执行: $audit_resp"
fi

section "Verify Summary And Monitor"
summary_resp="$(curl -sS "${API_BASE}/tasks/${task_id}/agent-runs/summary")"
summary_subtask_type="$(printf '%s' "$summary_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); items=data.get("specialist_subtask_types") or []; print(items[0] if items else "")')"
if [[ "$summary_subtask_type" == "readonly_source_snapshot" ]]; then
  pass "task summary 暴露 readonly_source_snapshot specialist 类型"
else
  fail "task summary 未暴露 readonly_source_snapshot: $summary_resp"
fi

monitor_resp="$(curl -sS "${API_BASE}/monitor/overview")"
monitor_source_snapshot_count="$(printf '%s' "$monitor_resp" | extract_json_field "agent_metrics.specialist_subtasks_by_type.readonly_source_snapshot" | tr -d '"')"
if [[ "$monitor_source_snapshot_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "monitor/overview 聚合了 readonly_source_snapshot specialist 数量"
else
  fail "monitor/overview 未聚合 readonly_source_snapshot specialist 数量: $monitor_resp"
fi

section "Done"
log "日志文件: $LOG_FILE"
log "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT}"
if [[ "$FAIL_COUNT" -gt 0 ]]; then
  exit 1
fi
