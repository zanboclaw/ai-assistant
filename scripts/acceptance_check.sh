#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8000}"
WORKSPACE_BASE="${WORKSPACE_BASE:-/opt/ai-assistant/data/workspace}"
LOG_DIR="${LOG_DIR:-/opt/ai-assistant/logs}"
mkdir -p "$LOG_DIR"
mkdir -p "$WORKSPACE_BASE"

TS="$(date +%F_%H%M%S)"
LOG_FILE="${LOG_DIR}/acceptance_check_${TS}.log"

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

prepare_test_files() {
  section "准备测试文件"

  cat > "${WORKSPACE_BASE}/test_note.txt" <<'EOF'
这是一个测试文件。
里面记录了 Ubuntu 上个人 AI 助理项目的几个要点：
1. 先搭 API + worker + postgres
2. 再接入 DeepSeek 做 planner
3. 再接 web_search 和 file_read
EOF

  cat > "${WORKSPACE_BASE}/sample.json" <<'EOF'
{
  "name": "ai-assistant",
  "version": "1.0",
  "modules": ["api", "worker", "postgres"],
  "planner": "DeepSeek"
}
EOF

  pass "测试文件已准备完成"
}

post_task() {
  local user_input="$1"
  USER_INPUT="$user_input" python3 -c '
import json, os
print(json.dumps({"user_input": os.environ["USER_INPUT"]}, ensure_ascii=False))
' | curl -sS -X POST "${API_BASE}/tasks" \
    -H "Content-Type: application/json" \
    -d @-
}

extract_task_id() {
  python3 -c '
import json, sys
raw = sys.stdin.read().strip()
if not raw:
    print("")
    raise SystemExit(0)
try:
    data = json.loads(raw)
except Exception:
    print("")
    raise SystemExit(0)

if isinstance(data, dict):
    print(data.get("id", ""))
else:
    print("")
'
}

wait_for_task_final() {
  local task_id="$1"
  local max_wait="${2:-120}"
  local interval="${3:-2}"

  local start_ts now elapsed status resp
  start_ts="$(date +%s)"

  while true; do
    resp="$(curl -sS "${API_BASE}/tasks/${task_id}" || true)"

    status="$(
      printf '%s' "$resp" | python3 -c '
import json, sys
raw = sys.stdin.read().strip()
if not raw:
    print("")
    raise SystemExit(0)
try:
    data = json.loads(raw)
except Exception:
    print("")
    raise SystemExit(0)
print(data.get("status", ""))
'
    )"

    if [[ "$status" == "completed" || "$status" == "failed" ]]; then
      echo "$status"
      return 0
    fi

    now="$(date +%s)"
    elapsed=$((now - start_ts))
    if (( elapsed >= max_wait )); then
      echo "timeout"
      return 0
    fi

    sleep "$interval"
  done
}

check_task_summary() {
  local task_id="$1"

  section "任务摘要 task_id=${task_id}"

  local resp summary
  resp="$(curl -sS "${API_BASE}/tasks/${task_id}")"

  summary="$(
    printf '%s' "$resp" | python3 -c '
import json, sys
raw = sys.stdin.read().strip()

if not raw:
    print("ERROR: /tasks/{id} 返回为空")
    raise SystemExit(1)

try:
    task = json.loads(raw)
except Exception as e:
    print(f"ERROR: /tasks/{{id}} JSON 解析失败: {e}")
    raise SystemExit(1)

print(f"id={task.get(\"id\")}")
print(f"status={task.get(\"status\")}")
print(f"user_input={task.get(\"user_input\")}")
print(f"error_message={task.get(\"error_message\")}")
print("result:")
print(task.get("result"))
'
  )" || true

  echo "$summary" | tee -a "$LOG_FILE"

  if echo "$summary" | grep -q "^ERROR:"; then
    fail "任务摘要获取失败 task_id=${task_id}"
    return 1
  fi

  pass "任务摘要获取成功 task_id=${task_id}"
}

check_steps_protocol() {
  local task_id="$1"

  section "结构化协议校验 task_id=${task_id}"

  local raw
  raw="$(curl -sS "${API_BASE}/tasks/${task_id}/steps")"

  printf '%s' "$raw" | python3 -c '
import json, sys

raw = sys.stdin.read().strip()
if not raw:
    print("FAIL|steps 接口返回为空")
    raise SystemExit(0)

try:
    steps = json.loads(raw)
except Exception as e:
    print(f"FAIL|steps JSON 解析失败: {e}")
    raise SystemExit(0)

if not isinstance(steps, list) or not steps:
    print("FAIL|steps 为空")
    raise SystemExit(0)

deprecated_keys = {"file_path", "dir_path"}
deprecated_placeholders = {"[file_content]", "[summarized_content]"}

for s in steps:
    step_no = s.get("step_order")
    status = s.get("status")
    tool_name = s.get("tool_name")
    input_payload = s.get("input_payload")
    output_payload = s.get("output_payload")
    output_data = s.get("output_data")
    error_message = s.get("error_message")
    error_strategy = s.get("error_strategy")

    if status not in {"completed", "failed", "pending", "running"}:
        print(f"WARN|step {step_no} 状态异常: {status}")

    if "tool_name" not in s:
        print(f"FAIL|step {step_no} 缺少 tool_name 字段")
    elif not tool_name:
        print(f"WARN|step {step_no} tool_name 为空，可能走了 legacy/fallback")

    if "output_data" not in s:
        print(f"FAIL|step {step_no} 缺少 output_data 字段")

    if "error_strategy" not in s:
        print(f"FAIL|step {step_no} 缺少 error_strategy 字段")
    elif not error_strategy:
        print(f"WARN|step {step_no} error_strategy 为空")

    if not isinstance(input_payload, str) or not input_payload.strip():
        print(f"FAIL|step {step_no} input_payload 为空或非法")
    else:
        try:
            parsed = json.loads(input_payload)
            if not isinstance(parsed, dict):
                print(f"FAIL|step {step_no} input_payload 不是 JSON 对象")
            else:
                keys = set(parsed.keys())
                found_deprecated_keys = keys & deprecated_keys
                if found_deprecated_keys:
                    print(f"FAIL|step {step_no} 使用废弃字段: {sorted(found_deprecated_keys)}")

                def scan_value(v):
                    found = []
                    if isinstance(v, str):
                        for p in deprecated_placeholders:
                            if p in v:
                                found.append(p)
                    elif isinstance(v, dict):
                        for vv in v.values():
                            found.extend(scan_value(vv))
                    elif isinstance(v, list):
                        for vv in v:
                            found.extend(scan_value(vv))
                    return found

                bad_placeholders = []
                for v in parsed.values():
                    bad_placeholders.extend(scan_value(v))
                if bad_placeholders:
                    print(f"FAIL|step {step_no} 使用废弃占位符: {sorted(set(bad_placeholders))}")

        except Exception as e:
            print(f"FAIL|step {step_no} input_payload 不是合法 JSON: {e}")

    if isinstance(output_data, str) and output_data.strip():
        try:
            json.loads(output_data)
        except Exception as e:
            print(f"WARN|step {step_no} output_data 不是合法 JSON: {e}")

    for field_name, value in [("output_payload", output_payload), ("error_message", error_message)]:
        if isinstance(value, str):
            if "降级" in value:
                print(f"WARN|step {step_no} {field_name} 含有降级执行痕迹")
            if "[file_content]" in value or "[summarized_content]" in value:
                print(f"FAIL|step {step_no} {field_name} 含有废弃占位符")
            if "file_path" in value or "dir_path" in value:
                print(f"FAIL|step {step_no} {field_name} 含有废弃字段名")

print("PASS|steps 结构化协议校验完成")
' > /tmp/acceptance_protocol_check.txt

  while IFS= read -r line; do
    echo "$line" | tee -a "$LOG_FILE"
    if [[ "$line" == PASS\|* ]]; then
      pass "${line#PASS|}"
    elif [[ "$line" == FAIL\|* ]]; then
      fail "${line#FAIL|}"
    elif [[ "$line" == WARN\|* ]]; then
      warn "${line#WARN|}"
    fi
  done < /tmp/acceptance_protocol_check.txt
}

assert_step_tool() {
  local task_id="$1"
  local step_order="$2"
  local expected_tool="$3"

  local raw actual
  raw="$(curl -sS "${API_BASE}/tasks/${task_id}/steps")"

  actual="$(
    printf '%s' "$raw" | python3 -c '
import json, sys
step_order = int(sys.argv[1])
raw = sys.stdin.read().strip()

try:
    steps = json.loads(raw)
except Exception:
    print("")
    raise SystemExit(0)

for s in steps:
    if int(s.get("step_order", 0)) == step_order:
        print(s.get("tool_name", ""))
        raise SystemExit(0)

print("")
' "$step_order"
  )"

  if [[ "$actual" == "$expected_tool" ]]; then
    pass "step ${step_order} tool_name 正确: ${expected_tool}"
  else
    fail "step ${step_order} tool_name 不正确: 期望=${expected_tool} 实际=${actual}"
  fi
}

assert_step_output_contains() {
  local task_id="$1"
  local step_order="$2"
  local keyword="$3"

  local raw matched
  raw="$(curl -sS "${API_BASE}/tasks/${task_id}/steps")"

  matched="$(
    printf '%s' "$raw" | python3 -c '
import json, sys
step_order = int(sys.argv[1])
keyword = sys.argv[2]
raw = sys.stdin.read().strip()

try:
    steps = json.loads(raw)
except Exception:
    print("0")
    raise SystemExit(0)

for s in steps:
    if int(s.get("step_order", 0)) == step_order:
        text = s.get("output_payload") or ""
        print("1" if keyword in text else "0")
        raise SystemExit(0)

print("0")
' "$step_order" "$keyword"
  )"

  if [[ "$matched" == "1" ]]; then
    pass "step ${step_order} output_payload 包含关键词: ${keyword}"
  else
    fail "step ${step_order} output_payload 不包含关键词: ${keyword}"
  fi
}

assert_step_input_contains() {
  local task_id="$1"
  local step_order="$2"
  local keyword="$3"

  local raw matched
  raw="$(curl -sS "${API_BASE}/tasks/${task_id}/steps")"

  matched="$(
    printf '%s' "$raw" | python3 -c '
import json, sys
step_order = int(sys.argv[1])
keyword = sys.argv[2]
raw = sys.stdin.read().strip()

try:
    steps = json.loads(raw)
except Exception:
    print("0")
    raise SystemExit(0)

for s in steps:
    if int(s.get("step_order", 0)) == step_order:
        text = s.get("input_payload") or ""
        print("1" if keyword in text else "0")
        raise SystemExit(0)

print("0")
' "$step_order" "$keyword"
  )"

  if [[ "$matched" == "1" ]]; then
    pass "step ${step_order} input_payload 包含关键词: ${keyword}"
  else
    fail "step ${step_order} input_payload 不包含关键词: ${keyword}"
  fi
}

check_file_exists_and_keywords() {
  local file_path="$1"
  shift
  local keywords=("$@")

  section "目标文件校验 ${file_path}"

  if [[ ! -f "$file_path" ]]; then
    fail "目标文件不存在: $file_path"
    return 1
  fi

  pass "目标文件存在: $file_path"

  local content
  content="$(cat "$file_path")"
  echo "$content" | tee -a "$LOG_FILE"

  for kw in "${keywords[@]}"; do
    if grep -q "$kw" "$file_path"; then
      pass "目标文件包含关键词: $kw"
    else
      fail "目标文件缺少关键词: $kw"
    fi
  done
}

run_case_read_summarize_write() {
  section "用例1：读取文件 -> 整理要点 -> 写入文件"

  local target_file="${WORKSPACE_BASE}/output_summary_acceptance.md"
  rm -f "$target_file"

  local user_input="读取文件 /workspace/test_note.txt 并整理要点后写入 /workspace/output_summary_acceptance.md"
  local post_resp task_id final_status

  post_resp="$(post_task "$user_input")"
  echo "$post_resp" | tee -a "$LOG_FILE"

  task_id="$(printf '%s' "$post_resp" | extract_task_id)"
  if [[ -z "$task_id" ]]; then
    fail "创建任务失败：未获取到 task_id"
    return 1
  fi
  pass "任务创建成功 task_id=${task_id}"

  final_status="$(wait_for_task_final "$task_id" 180 2)"
  log "任务最终状态: task_id=${task_id} status=${final_status}"

  if [[ "$final_status" == "completed" ]]; then
    pass "任务完成 task_id=${task_id}"
  elif [[ "$final_status" == "failed" ]]; then
    fail "任务失败 task_id=${task_id}"
  else
    fail "任务超时未完成 task_id=${task_id}"
  fi

  check_task_summary "$task_id"
  check_steps_protocol "$task_id"
  assert_step_tool "$task_id" 1 "file_read"
  assert_step_tool "$task_id" 2 "summarize_text"
  assert_step_tool "$task_id" 3 "file_write"

  check_file_exists_and_keywords \
    "$target_file" \
    "摘要结果" \
    "API" \
    "DeepSeek" \
    "web_search"
}

run_case_shell_exec() {
  section "用例2：执行命令 -> 整理输出"

  local user_input='执行命令 `ls /workspace` 并整理输出'
  local post_resp task_id final_status

  post_resp="$(post_task "$user_input")"
  echo "$post_resp" | tee -a "$LOG_FILE"

  task_id="$(printf '%s' "$post_resp" | extract_task_id)"
  if [[ -z "$task_id" ]]; then
    fail "创建 shell 任务失败：未获取到 task_id"
    return 1
  fi
  pass "shell 任务创建成功 task_id=${task_id}"

  final_status="$(wait_for_task_final "$task_id" 120 2)"
  log "shell 任务最终状态: task_id=${task_id} status=${final_status}"

  if [[ "$final_status" == "completed" ]]; then
    pass "shell 任务完成 task_id=${task_id}"
  elif [[ "$final_status" == "failed" ]]; then
    fail "shell 任务失败 task_id=${task_id}"
  else
    fail "shell 任务超时未完成 task_id=${task_id}"
  fi

  check_task_summary "$task_id"
  check_steps_protocol "$task_id"
  assert_step_tool "$task_id" 1 "shell_exec"
  assert_step_tool "$task_id" 2 "summarize_text"
  assert_step_output_contains "$task_id" 1 "/workspace"
}

run_case_read_json_summary() {
  section "用例3：读取 JSON -> 整理要点"

  local user_input='读取 JSON 文件 /workspace/sample.json 并整理要点'
  local post_resp task_id final_status

  post_resp="$(post_task "$user_input")"
  echo "$post_resp" | tee -a "$LOG_FILE"

  task_id="$(printf '%s' "$post_resp" | extract_task_id)"
  if [[ -z "$task_id" ]]; then
    fail "创建 JSON 摘要任务失败：未获取到 task_id"
    return 1
  fi
  pass "JSON 摘要任务创建成功 task_id=${task_id}"

  final_status="$(wait_for_task_final "$task_id" 120 2)"
  log "JSON 摘要任务最终状态: task_id=${task_id} status=${final_status}"

  if [[ "$final_status" == "completed" ]]; then
    pass "JSON 摘要任务完成 task_id=${task_id}"
  elif [[ "$final_status" == "failed" ]]; then
    fail "JSON 摘要任务失败 task_id=${task_id}"
  else
    fail "JSON 摘要任务超时未完成 task_id=${task_id}"
  fi

  check_task_summary "$task_id"
  check_steps_protocol "$task_id"
  assert_step_tool "$task_id" 1 "read_json"
  assert_step_tool "$task_id" 2 "summarize_text"
  assert_step_output_contains "$task_id" 1 "read_json 成功"
}

run_case_read_write_json() {
  section "用例4：读取 JSON -> 写入 JSON"

  local target_file="${WORKSPACE_BASE}/sample_copy_acceptance.json"
  rm -f "$target_file"

  local user_input='读取 JSON 文件 /workspace/sample.json 并原样写入 JSON 文件 /workspace/sample_copy_acceptance.json'
  local post_resp task_id final_status

  post_resp="$(post_task "$user_input")"
  echo "$post_resp" | tee -a "$LOG_FILE"

  task_id="$(printf '%s' "$post_resp" | extract_task_id)"
  if [[ -z "$task_id" ]]; then
    fail "创建 JSON 写入任务失败：未获取到 task_id"
    return 1
  fi
  pass "JSON 写入任务创建成功 task_id=${task_id}"

  final_status="$(wait_for_task_final "$task_id" 120 2)"
  log "JSON 写入任务最终状态: task_id=${task_id} status=${final_status}"

  if [[ "$final_status" == "completed" ]]; then
    pass "JSON 写入任务完成 task_id=${task_id}"
  elif [[ "$final_status" == "failed" ]]; then
    fail "JSON 写入任务失败 task_id=${task_id}"
  else
    fail "JSON 写入任务超时未完成 task_id=${task_id}"
  fi

  check_task_summary "$task_id"
  check_steps_protocol "$task_id"
  assert_step_tool "$task_id" 1 "read_json"
  assert_step_tool "$task_id" 2 "write_json"

  check_file_exists_and_keywords \
    "$target_file" \
    "\"name\": \"ai-assistant\"" \
    "\"planner\": \"DeepSeek\""
}

run_case_http_get() {
  section "用例5：http GET -> 整理返回结果"

  local user_input='请求 https://httpbin.org/get 并整理返回结果'
  local post_resp task_id final_status

  post_resp="$(post_task "$user_input")"
  echo "$post_resp" | tee -a "$LOG_FILE"

  task_id="$(printf '%s' "$post_resp" | extract_task_id)"
  if [[ -z "$task_id" ]]; then
    fail "创建 http GET 任务失败：未获取到 task_id"
    return 1
  fi
  pass "http GET 任务创建成功 task_id=${task_id}"

  final_status="$(wait_for_task_final "$task_id" 120 2)"
  log "http GET 任务最终状态: task_id=${task_id} status=${final_status}"

  if [[ "$final_status" == "completed" ]]; then
    pass "http GET 任务完成 task_id=${task_id}"
  elif [[ "$final_status" == "failed" ]]; then
    fail "http GET 任务失败 task_id=${task_id}"
  else
    fail "http GET 任务超时未完成 task_id=${task_id}"
  fi

  check_task_summary "$task_id"
  check_steps_protocol "$task_id"
  assert_step_tool "$task_id" 1 "http_request"
  assert_step_tool "$task_id" 2 "summarize_text"
  assert_step_output_contains "$task_id" 1 "状态码：200"
}

run_case_http_post() {
  section "用例6：http POST -> 整理返回结果"

  local user_input='向 https://httpbin.org/post 提交数据并整理结果'
  local post_resp task_id final_status

  post_resp="$(post_task "$user_input")"
  echo "$post_resp" | tee -a "$LOG_FILE"

  task_id="$(printf '%s' "$post_resp" | extract_task_id)"
  if [[ -z "$task_id" ]]; then
    fail "创建 http POST 任务失败：未获取到 task_id"
    return 1
  fi
  pass "http POST 任务创建成功 task_id=${task_id}"

  final_status="$(wait_for_task_final "$task_id" 120 2)"
  log "http POST 任务最终状态: task_id=${task_id} status=${final_status}"

  if [[ "$final_status" == "completed" ]]; then
    pass "http POST 任务完成 task_id=${task_id}"
  elif [[ "$final_status" == "failed" ]]; then
    fail "http POST 任务失败 task_id=${task_id}"
  else
    fail "http POST 任务超时未完成 task_id=${task_id}"
  fi

  check_task_summary "$task_id"
  check_steps_protocol "$task_id"
  assert_step_tool "$task_id" 1 "http_request"
  assert_step_tool "$task_id" 2 "summarize_text"
  assert_step_input_contains "$task_id" 1 "\"method\": \"POST\""
  assert_step_input_contains "$task_id" 1 "\"json\":"
  assert_step_output_contains "$task_id" 1 "状态码：200"
}

main() {
  : > "$LOG_FILE"

  section "基础环境检查"
  require_cmd curl
  require_cmd python3

  section "API 健康检查"
  if curl -sS "${API_BASE}/tasks" >/dev/null; then
    pass "API 可访问: ${API_BASE}/tasks"
  else
    fail "API 不可访问: ${API_BASE}/tasks"
    exit 1
  fi

  prepare_test_files

  run_case_read_summarize_write
  run_case_shell_exec
  run_case_read_json_summary
  run_case_read_write_json
  run_case_http_get
  run_case_http_post

  section "验收汇总"
  log "PASS=${PASS_COUNT} WARN=${WARN_COUNT} FAIL=${FAIL_COUNT}"
  log "日志文件: ${LOG_FILE}"

  if (( FAIL_COUNT > 0 )); then
    exit 1
  fi
}

main "$@"