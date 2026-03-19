#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-${ROOT_DIR}/logs}"
API_BASE="${API_BASE:-http://localhost:8000}"
mkdir -p "$LOG_DIR"
source "${ROOT_DIR}/scripts/http_fallback.sh"

TS="$(date +%F_%H%M%S)"
LOG_FILE="${LOG_DIR}/task_runtime_mainline_init_check_${TS}.log"

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

section "Create Mainline Init Task"
task_resp="$(python3 - <<'PY' | api_request_stdin POST "/tasks" "local_admin"
import json
print(json.dumps({
    "user_input": "执行命令 `sleep 5` 并整理输出"
}, ensure_ascii=False))
PY
)"
task_id="$(printf '%s' "$task_resp" | extract_json_field "id" | tr -d '"')"
if [[ "$task_id" =~ ^[0-9]+$ ]]; then
  pass "成功创建 mainline init smoke task #$task_id"
else
  fail "创建 mainline init smoke task 失败: $task_resp"
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

if [[ "$task_status" == "waiting_approval" || "$task_status" == "running" ]]; then
  pass "任务在终态前进入可观测状态 status=${task_status}"
elif [[ "$task_status" == "completed" || "$task_status" == "failed" ]]; then
  warn "任务过快进入终态，仍继续检查 Stage 5 主链摘要 status=${task_status}"
else
  fail "任务未进入 waiting_approval/running/completed/failed: ${task_state}"
fi

section "Verify Pre Terminal Stage 5 Summary"
stage5_exists="$(printf '%s' "$task_state" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(bool(data.get("stage5")))')"
stage5_impl="$(printf '%s' "$task_state" | extract_json_field "stage5.implementation_status" | tr -d '"')"
stage5_origin="$(printf '%s' "$task_state" | extract_json_field "stage5.record_origin" | tr -d '"')"
stage5_control_mode="$(printf '%s' "$task_state" | extract_json_field "stage5.control_mode" | tr -d '"')"
stage5_backend="$(printf '%s' "$task_state" | extract_json_field "stage5.execution_backend" | tr -d '"')"
stage5_runtime_fanout="$(printf '%s' "$task_state" | extract_json_field "stage5.runtime_fanout_active" | tr -d '"')"
stage5_role_counts="$(printf '%s' "$task_state" | extract_json_field "stage5.role_counts")"
stage5_latest_eval_source="$(printf '%s' "$task_state" | extract_json_field "stage5.latest_evaluator_source" | tr -d '"')"
stage5_manager_count="$(printf '%s' "$stage5_role_counts" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(int(data.get("manager") or 0))')"
stage5_specialist_count="$(printf '%s' "$stage5_role_counts" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(int(data.get("specialist") or 0))')"
stage5_reviewer_count="$(printf '%s' "$stage5_role_counts" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(int(data.get("reviewer") or 0))')"

if [[ "$stage5_exists" == "True" && "$stage5_impl" == "task_runtime_postrun_v1" && ( "$stage5_origin" == "mainline_postrun" || "$stage5_origin" == "mainline_runtime" ) && "$stage5_control_mode" == "observe_only" && "$stage5_backend" == "mainline" ]]; then
  pass "任务在终态前已暴露主链 Stage 5 summary"
else
  fail "任务在终态前未暴露预期 Stage 5 summary: ${task_state}"
fi

if [[ "$stage5_manager_count" -ge 1 && "$stage5_specialist_count" -ge 1 && "$stage5_reviewer_count" -ge 1 ]]; then
  pass "任务在终态前已初始化 manager/specialist/reviewer 骨架"
else
  fail "任务在终态前的 Stage 5 角色骨架不完整: role_counts=${stage5_role_counts}"
fi

if [[ -z "$stage5_latest_eval_source" ]]; then
  pass "任务在终态前尚未写入 evaluator source，符合初始化预期"
else
  fail "任务在终态前不应已有 evaluator source: ${task_state}"
fi

if [[ "$stage5_runtime_fanout" == "true" || "$stage5_runtime_fanout" == "True" || "$stage5_origin" == "mainline_runtime" ]]; then
  pass "任务在终态前已进入 mainline runtime fanout 可观测状态"
else
  warn "任务在终态前仍未观测到 runtime fanout 标记，继续检查终态收口"
fi

section "Approve Pending Task If Needed"
approval_done="false"
if [[ "$task_status" == "waiting_approval" ]]; then
  approvals_resp="$(api_request GET "/tasks/${task_id}/approvals")"
  approval_id="$(printf '%s' "$approvals_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); pending=next((item for item in data if item.get("status")=="pending"), {}); print(pending.get("id") or "")')"
  if [[ "$approval_id" =~ ^[0-9]+$ ]]; then
    approve_resp="$(api_request POST "/approvals/${approval_id}/approve" '{"note":"task runtime mainline init smoke approve"}' "local_admin")"
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
      approve_resp="$(api_request POST "/approvals/${approval_id}/approve" '{"note":"task runtime mainline init smoke approve"}' "local_admin")"
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
