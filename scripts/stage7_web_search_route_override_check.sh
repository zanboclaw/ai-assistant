#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-${ROOT_DIR}/logs}"
API_BASE="${API_BASE:-http://127.0.0.1:8000}"
HTTP_FALLBACK_CURL_MAX_TIME="${HTTP_FALLBACK_CURL_MAX_TIME:-120}"
mkdir -p "$LOG_DIR"
source "${ROOT_DIR}/scripts/http_fallback.sh"

TS="$(date +%F_%H%M%S)"
LOG_FILE="${LOG_DIR}/stage7_web_search_route_override_check_${TS}.log"

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

select_step_field_by_tool_name() {
  local tool_name="$1"
  local field="$2"
  python3 -c 'import json, sys
tool_name = sys.argv[1]
field = sys.argv[2]
data = json.load(sys.stdin)
item = next((entry for entry in data if str(entry.get("tool_name") or "") == tool_name), {})
value = item
for part in field.split("."):
    if isinstance(value, dict):
        value = value.get(part)
    elif isinstance(value, str) and value.strip().startswith(("{", "[")):
        try:
            value = json.loads(value)
        except Exception:
            value = None
            break
        if isinstance(value, dict):
            value = value.get(part)
        else:
            value = None
            break
    else:
        value = None
        break
print(json.dumps(value, ensure_ascii=False))' "$tool_name" "$field"
}

wait_task_terminal() {
  local task_id="$1"
  local approval_note="$2"
  local task_status=""
  local task_state=""
  local approval_done="false"

  for _ in $(seq 1 240); do
    task_state="$(api_request GET "/tasks/${task_id}")"
    task_status="$(printf '%s' "$task_state" | extract_json_field "status" | tr -d '"')"
    if [[ "$task_status" == "waiting_approval" && "$approval_done" != "true" ]]; then
      approvals_resp="$(api_request GET "/tasks/${task_id}/approvals")"
      approval_id="$(printf '%s' "$approvals_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); pending=next((item for item in data if item.get("status")=="pending"), {}); print(pending.get("id") or "")')"
      if [[ "$approval_id" =~ ^[0-9]+$ ]]; then
        approve_resp="$(api_request POST "/approvals/${approval_id}/approve" "{\"note\":\"${approval_note}\"}" "local_admin")"
        if echo "$approve_resp" | grep -q '"approval approved"'; then
          pass "已批准 task 审批 approval_id=${approval_id}"
          approval_done="true"
        else
          fail "task 审批批准异常: ${approve_resp}"
        fi
      fi
    fi
    if [[ "$task_status" == "completed" || "$task_status" == "failed" ]]; then
      break
    fi
    sleep 1
  done

  if [[ "$task_status" == "completed" || "$task_status" == "failed" ]]; then
    pass "task 进入终态 status=${task_status}"
  else
    fail "task 未进入终态: ${task_state}"
  fi
}

section "Init DB"
api_request POST "/init-db" "" "local_admin" >/dev/null
pass "数据库初始化成功"

section "Create Baseline Task"
baseline_task_id=""
baseline_prompt=""
baseline_steps_resp=""

baseline_prompt="帮我查一下A股有多少家公司"
task_resp="$(python3 - <<'PY' "$baseline_prompt" | api_request_stdin POST "/tasks" "local_admin"
import json, sys
print(json.dumps({
    "user_input": sys.argv[1],
}, ensure_ascii=False))
PY
)"
baseline_task_id="$(printf '%s' "$task_resp" | extract_json_field "id" | tr -d '"')"
if [[ ! "$baseline_task_id" =~ ^[0-9]+$ ]]; then
  fail "创建 baseline web_search task 失败: ${task_resp}"
  log "日志文件: ${LOG_FILE}"
  log "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT} WARN=${WARN_COUNT}"
  exit 1
fi
pass "成功创建 baseline web_search task #${baseline_task_id}"

wait_task_terminal "$baseline_task_id" "stage7 web_search override smoke approve"

baseline_steps_resp="$(api_request GET "/tasks/${baseline_task_id}/steps")"
web_search_tool="$(printf '%s' "$baseline_steps_resp" | select_step_field_by_tool_name "web_search" "tool_name" | tr -d '"')"
web_search_result_count="$(printf '%s' "$baseline_steps_resp" | select_step_field_by_tool_name "web_search" "output_data.result_count" | tr -d '"')"
if [[ "$web_search_tool" == "web_search" && "$web_search_result_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "baseline task 已命中 web_search 且返回结果数=${web_search_result_count}"
else
  fail "baseline task 未获得可用 web_search 结果: ${baseline_steps_resp}"
  log "日志文件: ${LOG_FILE}"
  log "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT} WARN=${WARN_COUNT}"
  exit 1
fi

section "Resolve Workflow Proposal"
proposal_resp="$(api_request GET "/tasks/${baseline_task_id}/workflow-proposals/latest")"
proposal_id="$(printf '%s' "$proposal_resp" | extract_json_field "id" | tr -d '"')"
proposal_source="$(printf '%s' "$proposal_resp" | extract_json_field "source" | tr -d '"')"
if [[ "$proposal_id" =~ ^[0-9]+$ && "$proposal_source" == "task_runtime_postrun_v1" ]]; then
  pass "baseline task 已产出主链 workflow proposal #${proposal_id}"
else
  fail "workflow proposal 解析异常: ${proposal_resp}"
fi

section "Create Workflow Improvement Change Request"
override_tokens=1666
change_resp="$(python3 - <<'PY' "$proposal_id" "$override_tokens" | api_request_stdin POST "/workflow-proposals/${proposal_id}/change-request-draft" "local_admin"
import json, sys
proposal_id = sys.argv[1]
override_tokens = int(sys.argv[2])
print(json.dumps({
    "target_type": "model_route",
    "target_key": "web_search_summary",
    "proposed_payload": {
        "provider": "deepseek_default",
        "model_name": "deepseek-chat",
        "temperature": 0.2,
        "max_tokens": override_tokens,
        "enabled": True,
        "description": "stage7 web_search_summary override smoke route"
    },
    "rationale": "stage7 web_search_summary override smoke create-change"
}, ensure_ascii=False))
PY
)"
change_request_id="$(printf '%s' "$change_resp" | extract_json_field "change_request.id" | tr -d '"')"
change_request_status="$(printf '%s' "$change_resp" | extract_json_field "change_request.status" | tr -d '"')"
if [[ "$change_request_id" =~ ^[0-9]+$ && "$change_request_status" == "pending" ]]; then
  pass "成功创建 web_search_summary workflow_improvement change request #${change_request_id}"
else
  fail "创建 web_search_summary workflow_improvement change request 失败: ${change_resp}"
fi

approve_resp="$(api_request POST "/change-requests/${change_request_id}/approve" '{"note":"stage7 web_search_summary override approve"}' "local_admin")"
approved_status="$(printf '%s' "$approve_resp" | extract_json_field "status" | tr -d '"')"
if [[ "$approved_status" == "approved" ]]; then
  pass "web_search_summary change request 已批准"
else
  fail "web_search_summary change request 批准异常: ${approve_resp}"
fi

section "Run Change-Scoped Shadow Validation"
shadow_resp="$(python3 - <<'PY' | api_request_stdin POST "/change-requests/${change_request_id}/shadow-validate" "local_admin"
import json
print(json.dumps({
    "note": "stage7 web_search_summary override validation",
    "await_completion": False,
    "timeout_seconds": 120,
    "poll_interval_seconds": 1.0
}, ensure_ascii=False))
PY
)"
shadow_task_id="$(printf '%s' "$shadow_resp" | extract_json_field "shadow_task.id" | tr -d '"')"
shadow_tracking_mode="$(printf '%s' "$shadow_resp" | extract_json_field "tracking_mode" | tr -d '"')"
if [[ "$shadow_task_id" =~ ^[0-9]+$ && "$shadow_tracking_mode" == "async_background_wait" ]]; then
  pass "web_search_summary shadow validation 已异步启动 shadow_task_id=${shadow_task_id}"
else
  fail "web_search_summary shadow validation 启动异常: ${shadow_resp}"
fi

proposal_shadow_resp=""
proposal_shadow_status=""
proposal_shadow_task_id=""
for _ in $(seq 1 240); do
  proposal_shadow_resp="$(api_request GET "/workflow-proposals/${proposal_id}/shadow-validation?history_limit=8" "" "local_admin")"
  proposal_shadow_status="$(printf '%s' "$proposal_shadow_resp" | extract_json_field "status" | tr -d '"')"
  proposal_shadow_task_id="$(printf '%s' "$proposal_shadow_resp" | extract_json_field "latest_shadow_task.id" | tr -d '"')"
  if [[ "$proposal_shadow_status" == "completed" ]]; then
    break
  fi
  sleep 1
done

proposal_shadow_result="$(printf '%s' "$proposal_shadow_resp" | extract_json_field "latest_validation.validation.validation_result" | tr -d '"')"
if [[ "$proposal_shadow_status" == "completed" && "$proposal_shadow_task_id" == "$shadow_task_id" ]]; then
  pass "web_search_summary shadow validation 已完成 shadow_task_id=${shadow_task_id}"
else
  fail "web_search_summary shadow validation 未完成或 shadow_task 不对齐: ${proposal_shadow_resp}"
fi
if [[ "$proposal_shadow_result" == "matched" || "$proposal_shadow_result" == "improved" || "$proposal_shadow_result" == "regressed" || "$proposal_shadow_result" == "changed" ]]; then
  pass "shadow validation 已返回可读比较结果 result=${proposal_shadow_result}"
else
  fail "web_search_summary shadow validation 结果异常: ${proposal_shadow_resp}"
fi

change_shadow_resp="$(api_request GET "/change-requests/${change_request_id}/shadow-validation?history_limit=8" "" "local_admin")"
change_shadow_status="$(printf '%s' "$change_shadow_resp" | extract_json_field "change_request.shadow_validation_status" | tr -d '"')"
change_shadow_ready="$(printf '%s' "$change_shadow_resp" | extract_json_field "change_request.shadow_validation_ready_to_apply" | tr -d '"')"
change_shadow_match="$(printf '%s' "$change_shadow_resp" | extract_json_field "change_request.shadow_validation_report.candidate_match" | tr -d '"')"
if [[ "$change_shadow_status" == "completed" && "$change_shadow_ready" == "true" && "$change_shadow_match" == "true" ]]; then
  pass "web_search_summary change request 已同步 completed shadow gate"
else
  fail "web_search_summary change request shadow gate 未同步: ${change_shadow_resp}"
fi

section "Verify Shadow Task Web Search Step"
shadow_steps_resp="$(api_request GET "/tasks/${proposal_shadow_task_id}/steps")"
shadow_web_search_tool="$(printf '%s' "$shadow_steps_resp" | select_step_field_by_tool_name "web_search" "tool_name" | tr -d '"')"
shadow_search_provider="$(printf '%s' "$shadow_steps_resp" | select_step_field_by_tool_name "web_search" "output_data.search_provider" | tr -d '"')"
shadow_result_count="$(printf '%s' "$shadow_steps_resp" | select_step_field_by_tool_name "web_search" "output_data.result_count" | tr -d '"')"
shadow_summary_backend="$(printf '%s' "$shadow_steps_resp" | select_step_field_by_tool_name "web_search" "output_data.summary_backend" | tr -d '"')"
shadow_summary_route_name="$(printf '%s' "$shadow_steps_resp" | select_step_field_by_tool_name "web_search" "output_data.summary_model_route.route_name" | tr -d '"')"
shadow_summary_route_tokens="$(printf '%s' "$shadow_steps_resp" | select_step_field_by_tool_name "web_search" "output_data.summary_model_route.max_tokens" | tr -d '"')"
if [[ "$shadow_web_search_tool" == "web_search" ]]; then
  pass "shadow task 已执行 web_search 步骤"
else
  fail "shadow task 未执行 web_search 步骤: ${shadow_steps_resp}"
fi
if [[ -n "$shadow_search_provider" && "$shadow_result_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "web_search 步骤输出已包含 provider=${shadow_search_provider} result_count=${shadow_result_count}"
else
  fail "web_search 步骤未返回可用搜索元数据: ${shadow_steps_resp}"
fi
if [[ "$shadow_summary_route_name" == "web_search_summary" && "$shadow_summary_route_tokens" == "${override_tokens}" && -n "$shadow_summary_backend" ]]; then
  pass "web_search 步骤输出已记录 override route 元数据 backend=${shadow_summary_backend}"
else
  fail "web_search 步骤未记录预期 summary route 元数据: ${shadow_steps_resp}"
fi

section "Done"
log "baseline prompt: ${baseline_prompt}"
log "日志文件: ${LOG_FILE}"
log "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT} WARN=${WARN_COUNT}"

if (( FAIL_COUNT > 0 )); then
  exit 1
fi
