#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-${ROOT_DIR}/logs}"
mkdir -p "$LOG_DIR"

TS="$(date +%F_%H%M%S)"
LOG_FILE="${LOG_DIR}/multi_agent_schema_check_${TS}.log"

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
init_resp="$(curl -sS -X POST "http://localhost:8000/init-db" -H "X-Actor-Name: local_admin")"
if [[ "$init_resp" == *"database initialized"* ]]; then
  pass "数据库初始化成功"
else
  fail "数据库初始化失败: $init_resp"
fi

section "Runtime Metadata"
runtime_resp="$(curl -sS "http://localhost:8000/runtime-metadata")"
multi_agent_version="$(printf '%s' "$runtime_resp" | extract_json_field "multi_agent_protocol.version" | tr -d '"')"
implementation_status="$(printf '%s' "$runtime_resp" | extract_json_field "multi_agent_protocol.implementation_status" | tr -d '"')"
evaluator_version="$(printf '%s' "$runtime_resp" | extract_json_field "evaluator_protocol.version" | tr -d '"')"
evaluator_status="$(printf '%s' "$runtime_resp" | extract_json_field "evaluator_protocol.implementation_status" | tr -d '"')"
if [[ "$multi_agent_version" == "multi-agent-v1" ]]; then
  pass "runtime metadata 暴露 multi-agent 协议版本"
else
  fail "runtime metadata 未返回预期协议版本: $runtime_resp"
fi
if [[ "$implementation_status" == "task_runtime_postrun_v1" ]]; then
  pass "runtime metadata 标记当前 multi-agent 已进入主链 postrun"
else
  fail "runtime metadata 未返回预期实现状态: $runtime_resp"
fi
if [[ "$evaluator_version" == "stage6-evaluator-v1" ]]; then
  pass "runtime metadata 暴露 evaluator 协议版本"
else
  fail "runtime metadata 未返回 evaluator 协议版本: $runtime_resp"
fi
if [[ "$evaluator_status" == "task_runtime_postrun_v1" ]]; then
  pass "runtime metadata 标记当前 evaluator 已进入主链 postrun"
else
  fail "runtime metadata 未返回预期 evaluator 实现状态: $runtime_resp"
fi

section "Agent Run APIs"
agent_runs_resp="$(curl -sS "http://localhost:8000/agent-runs")"
if [[ "$agent_runs_resp" == "[]" ]]; then
  pass "agent-runs 列表接口可用并返回空列表"
else
  warn "agent-runs 列表已存在数据: $agent_runs_resp"
fi

task_agent_runs_resp="$(curl -sS "http://localhost:8000/tasks/1/agent-runs" || true)"
if [[ "$task_agent_runs_resp" == "[]" ]] || [[ "$task_agent_runs_resp" == *"detail"* ]]; then
  pass "task 维度 agent-runs 接口可访问"
else
  warn "task 维度 agent-runs 返回非预期内容: $task_agent_runs_resp"
fi

section "Monitor Overview"
monitor_resp="$(curl -sS "http://localhost:8000/monitor/overview")"
monitor_multi_agent_version="$(printf '%s' "$monitor_resp" | extract_json_field "runtime_metadata.multi_agent_protocol_version" | tr -d '"')"
total_agent_runs="$(printf '%s' "$monitor_resp" | extract_json_field "agent_metrics.total_agent_runs" | tr -d '"')"
subtask_counts="$(printf '%s' "$monitor_resp" | extract_json_field "agent_metrics.specialist_subtasks_by_type" | tr -d '\n')"
if [[ "$monitor_multi_agent_version" == "multi-agent-v1" ]]; then
  pass "monitor/overview 返回 multi-agent 协议版本"
else
  fail "monitor/overview 未返回 multi-agent 协议版本: $monitor_resp"
fi
if [[ "$total_agent_runs" =~ ^[0-9]+$ ]]; then
  pass "monitor/overview 返回 agent_metrics.total_agent_runs"
else
  fail "monitor/overview 未返回有效 agent_metrics.total_agent_runs: $monitor_resp"
fi
if [[ "$subtask_counts" == "null" ]]; then
  fail "monitor/overview 未返回 specialist_subtasks_by_type: $monitor_resp"
else
  pass "monitor/overview 返回 specialist_subtasks_by_type"
fi

section "Done"
log "日志文件: $LOG_FILE"
log "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT} WARN=${WARN_COUNT}"

if (( FAIL_COUNT > 0 )); then
  exit 1
fi
