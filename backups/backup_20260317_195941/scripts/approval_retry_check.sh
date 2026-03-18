#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8000}"
WORKSPACE_BASE="${WORKSPACE_BASE:-/opt/ai-assistant/data/workspace}"
LOG_DIR="${LOG_DIR:-/opt/ai-assistant/logs}"
mkdir -p "$LOG_DIR"
mkdir -p "$WORKSPACE_BASE"

TS="$(date +%F_%H%M%S)"
LOG_FILE="${LOG_DIR}/approval_retry_check_${TS}.log"

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

require_cmd() {
  local cmd="$1"
  if command -v "$cmd" >/dev/null 2>&1; then
    pass "命令存在: $cmd"
  else
    fail "缺少命令: $cmd"
    exit 1
  fi
}

post_json() {
  local method="$1"
  local url="$2"
  local body="${3:-}"

  if [[ -n "$body" ]]; then
    curl -sS -X "$method" "$url" \
      -H "Content-Type: application/json" \
      -d "$body"
  else
    curl -sS -X "$method" "$url"
  fi
}

extract_json_field() {
  local expr="$1"
  python3 -c '
import json, sys
expr = sys.argv[1]
raw = sys.stdin.read().strip()
if not raw:
    print("")
    raise SystemExit(0)
try:
    data = json.loads(raw)
except Exception:
    print("")
    raise SystemExit(0)

current = data
for part in expr.split("."):
    if isinstance(current, dict):
        current = current.get(part)
    elif isinstance(current, list) and part.isdigit():
        idx = int(part)
        current = current[idx] if 0 <= idx < len(current) else None
    else:
        current = None
        break

print("" if current is None else current)
' "$expr"
}

wait_for_task_status() {
  local task_id="$1"
  local expected_status="$2"
  local max_wait="${3:-120}"
  local interval="${4:-2}"

  local start_ts now elapsed resp status
  start_ts="$(date +%s)"

  while true; do
    resp="$(curl -sS "${API_BASE}/tasks/${task_id}" || true)"
    status="$(printf '%s' "$resp" | extract_json_field "status")"

    if [[ "$status" == "$expected_status" ]]; then
      echo "$status"
      return 0
    fi

    if [[ "$status" == "failed" && "$expected_status" != "failed" ]]; then
      echo "$status"
      return 0
    fi

    now="$(date +%s)"
    elapsed=$((now - start_ts))
    if (( elapsed >= max_wait )); then
      echo "${status:-timeout}"
      return 0
    fi

    sleep "$interval"
  done
}

wait_for_task_final() {
  local task_id="$1"
  local max_wait="${2:-180}"
  local interval="${3:-2}"

  local start_ts now elapsed resp status
  start_ts="$(date +%s)"

  while true; do
    resp="$(curl -sS "${API_BASE}/tasks/${task_id}" || true)"
    status="$(printf '%s' "$resp" | extract_json_field "status")"

    if [[ "$status" == "completed" || "$status" == "failed" ]]; then
      echo "$status"
      return 0
    fi

    now="$(date +%s)"
    elapsed=$((now - start_ts))
    if (( elapsed >= max_wait )); then
      echo "${status:-timeout}"
      return 0
    fi

    sleep "$interval"
  done
}

find_pending_approval_id() {
  local task_id="$1"
  curl -sS "${API_BASE}/tasks/${task_id}/approvals" | python3 -c '
import json, sys
raw = sys.stdin.read().strip()
if not raw:
    print("")
    raise SystemExit(0)
try:
    rows = json.loads(raw)
except Exception:
    print("")
    raise SystemExit(0)

for row in rows:
    if row.get("status") == "pending":
        print(row.get("id", ""))
        raise SystemExit(0)

print("")
'
}

assert_steps_have_new_fields() {
  local task_id="$1"
  local raw
  local start_ts now elapsed
  start_ts="$(date +%s)"

  while true; do
    raw="$(curl -sS "${API_BASE}/tasks/${task_id}/steps")"
    if printf '%s' "$raw" | python3 -c '
import json, sys
raw = sys.stdin.read().strip()
try:
    rows = json.loads(raw)
except Exception:
    print("0")
    raise SystemExit(0)
print("1" if isinstance(rows, list) and rows else "0")
' | grep -q '^1$'; then
      break
    fi

    now="$(date +%s)"
    elapsed=$((now - start_ts))
    if (( elapsed >= 30 )); then
      break
    fi
    sleep 1
  done

  printf '%s' "$raw" | python3 -c '
import json, sys
raw = sys.stdin.read().strip()
required = ["run_if", "skip_if", "retry_count", "max_retries", "error_strategy"]
try:
    steps = json.loads(raw)
except Exception as e:
    print(f"FAIL|steps JSON 解析失败: {e}")
    raise SystemExit(0)

if not isinstance(steps, list) or not steps:
    print("FAIL|steps 为空")
    raise SystemExit(0)

for step in steps:
    step_no = step.get("step_order")
    for field in required:
        if field not in step:
            print(f"FAIL|step {step_no} 缺少字段: {field}")

print("PASS|steps 包含新增字段")
' > /tmp/approval_retry_step_fields.txt

  while IFS= read -r line; do
    echo "$line" | tee -a "$LOG_FILE"
    if [[ "$line" == PASS\|* ]]; then
      pass "${line#PASS|}"
    elif [[ "$line" == FAIL\|* ]]; then
      fail "${line#FAIL|}"
    fi
  done < /tmp/approval_retry_step_fields.txt
}

check_approval_flow() {
  section "审批流验证"

  local target_file="${WORKSPACE_BASE}/approval_test.md"
  rm -f "$target_file"

  local user_input="读取文件 /workspace/test_note.txt 并整理要点后写入 /workspace/approval_test.md"
  local post_resp task_id waiting_status approval_id approve_resp final_status

  post_resp="$(post_json POST "${API_BASE}/tasks" "{\"user_input\":\"${user_input}\"}")"
  echo "$post_resp" | tee -a "$LOG_FILE"

  task_id="$(printf '%s' "$post_resp" | extract_json_field "id")"
  if [[ -z "$task_id" ]]; then
    fail "审批流任务创建失败：未获取到 task_id"
    return 1
  fi
  pass "审批流任务创建成功 task_id=${task_id}"

  assert_steps_have_new_fields "$task_id"

  waiting_status="$(wait_for_task_status "$task_id" "waiting_approval" 120 2)"
  if [[ "$waiting_status" == "waiting_approval" ]]; then
    pass "任务成功进入 waiting_approval task_id=${task_id}"
  else
    fail "任务未进入 waiting_approval，当前状态=${waiting_status}"
    return 1
  fi

  approval_id="$(find_pending_approval_id "$task_id")"
  if [[ -n "$approval_id" ]]; then
    pass "找到待审批记录 approval_id=${approval_id}"
  else
    fail "未找到待审批记录 task_id=${task_id}"
    return 1
  fi

  approve_resp="$(post_json POST "${API_BASE}/approvals/${approval_id}/approve" '{"note":"approval_retry_check"}')"
  echo "$approve_resp" | tee -a "$LOG_FILE"

  if [[ "$(printf '%s' "$approve_resp" | extract_json_field "message")" == "approval approved" ]]; then
    pass "审批接口返回成功 approval_id=${approval_id}"
  else
    fail "审批接口返回异常 approval_id=${approval_id}"
    return 1
  fi

  final_status="$(wait_for_task_final "$task_id" 180 2)"
  if [[ "$final_status" == "completed" ]]; then
    pass "审批后任务执行完成 task_id=${task_id}"
  else
    fail "审批后任务未完成，最终状态=${final_status}"
    return 1
  fi

  if [[ -f "$target_file" ]]; then
    pass "审批后目标文件已生成: $target_file"
  else
    fail "审批后目标文件未生成: $target_file"
  fi
}

check_retry_flow() {
  section "失败重试验证"

  local user_input="请求接口 https://not-exist.invalid 并整理返回结果"
  local post_resp task_id final_status step_summary

  post_resp="$(post_json POST "${API_BASE}/tasks" "{\"user_input\":\"${user_input}\"}")"
  echo "$post_resp" | tee -a "$LOG_FILE"

  task_id="$(printf '%s' "$post_resp" | extract_json_field "id")"
  if [[ -z "$task_id" ]]; then
    fail "重试验证任务创建失败：未获取到 task_id"
    return 1
  fi
  pass "重试验证任务创建成功 task_id=${task_id}"

  final_status="$(wait_for_task_final "$task_id" 180 2)"
  if [[ "$final_status" == "failed" || "$final_status" == "completed" ]]; then
    pass "重试验证任务已结束 task_id=${task_id} status=${final_status}"
  else
    fail "重试验证任务未结束 task_id=${task_id} status=${final_status}"
    return 1
  fi

  step_summary="$(
    curl -sS "${API_BASE}/tasks/${task_id}/steps" | python3 -c '
import json, sys
raw = sys.stdin.read().strip()
try:
    steps = json.loads(raw)
except Exception:
    print("FAIL|steps JSON 解析失败")
    raise SystemExit(0)

matched_retry = False
matched_counter = False

for step in steps:
    tool_name = step.get("tool_name")
    retry_count = int(step.get("retry_count") or 0)
    max_retries = int(step.get("max_retries") or 0)
    text = (step.get("output_payload") or "") + "\n" + (step.get("error_message") or "")
    if tool_name == "http_request":
        if max_retries >= 1:
            matched_counter = True
        if retry_count >= 1 or "已重试" in text:
            matched_retry = True

if matched_counter:
    print("PASS|http_request 步骤已配置重试次数")
else:
    print("FAIL|http_request 步骤未配置重试次数")

if matched_retry:
    print("PASS|http_request 步骤出现重试痕迹")
else:
    print("FAIL|http_request 步骤未观察到重试痕迹")
'
  )"

  while IFS= read -r line; do
    echo "$line" | tee -a "$LOG_FILE"
    if [[ "$line" == PASS\|* ]]; then
      pass "${line#PASS|}"
    elif [[ "$line" == FAIL\|* ]]; then
      fail "${line#FAIL|}"
    fi
  done <<< "$step_summary"
}

main() {
  section "基础检查"
  require_cmd curl
  require_cmd python3

  section "初始化数据库"
  local init_resp
  init_resp="$(post_json POST "${API_BASE}/init-db")"
  echo "$init_resp" | tee -a "$LOG_FILE"

  if [[ "$(printf '%s' "$init_resp" | extract_json_field "message")" == "database initialized" ]]; then
    pass "数据库初始化成功"
  else
    fail "数据库初始化失败"
    exit 1
  fi

  check_approval_flow
  check_retry_flow

  section "验收汇总"
  log "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT} WARN=${WARN_COUNT}"

  if (( FAIL_COUNT > 0 )); then
    exit 1
  fi
}

main "$@"
