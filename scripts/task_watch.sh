#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8000}"
REFRESH_SECONDS="${REFRESH_SECONDS:-2}"

TMP_TASKS_FILE="$(mktemp)"
TMP_STEPS_FILE="$(mktemp)"

cleanup() {
  rm -f "$TMP_TASKS_FILE" "$TMP_STEPS_FILE"
}
trap cleanup EXIT

fetch_tasks() {
  curl -s "${API_BASE}/tasks" > "$TMP_TASKS_FILE"
}

fetch_steps() {
  local task_id="$1"
  curl -s "${API_BASE}/tasks/${task_id}/steps" > "$TMP_STEPS_FILE"
}

get_latest_task_id() {
  fetch_tasks
  python3 - "$TMP_TASKS_FILE" <<'PY'
import json, sys

path = sys.argv[1]
try:
    raw = open(path, "r", encoding="utf-8").read().strip()
except Exception:
    print("")
    raise SystemExit(0)

if not raw:
    print("")
    raise SystemExit(0)

try:
    tasks = json.loads(raw)
except Exception:
    print("")
    raise SystemExit(0)

if not isinstance(tasks, list) or not tasks:
    print("")
    raise SystemExit(0)

print(tasks[0].get("id", ""))
PY
}

print_task_header() {
  local task_id="$1"
  fetch_tasks
  python3 - "$TMP_TASKS_FILE" "$task_id" <<'PY'
import json, sys

path = sys.argv[1]
task_id = sys.argv[2]

try:
    raw = open(path, "r", encoding="utf-8").read().strip()
except Exception:
    print("任务列表读取失败")
    raise SystemExit(0)

if not raw:
    print("任务列表为空")
    raise SystemExit(0)

try:
    tasks = json.loads(raw)
except Exception:
    print("任务列表解析失败")
    raise SystemExit(0)

target = None
for t in tasks:
    if str(t.get("id")) == str(task_id):
        target = t
        break

if not target:
    print(f"未找到任务 {task_id}")
    raise SystemExit(0)

print(f"任务ID: {target.get('id')}")
print(f"状态:   {target.get('status')}")
print(f"任务:   {target.get('user_input')}")
if target.get("error_message"):
    print(f"错误:   {target.get('error_message')}")
PY
}

print_task_steps() {
  local task_id="$1"
  fetch_steps "$task_id"
  python3 - "$TMP_STEPS_FILE" <<'PY'
import json, sys

path = sys.argv[1]
try:
    raw = open(path, "r", encoding="utf-8").read().strip()
except Exception:
    print("steps 读取失败")
    raise SystemExit(0)

if not raw:
    print("steps 为空")
    raise SystemExit(0)

try:
    steps = json.loads(raw)
except Exception:
    print("steps 解析失败")
    raise SystemExit(0)

if not isinstance(steps, list) or not steps:
    print("暂无 steps")
    raise SystemExit(0)

print("")
print("步骤:")
for s in steps:
    step_order = s.get("step_order")
    step_name = s.get("step_name")
    tool_name = s.get("tool_name")
    status = s.get("status")
    print(f"  [{step_order}] {step_name}")
    print(f"       tool={tool_name}  status={status}")

    output_payload = (s.get("output_payload") or "").strip()
    if output_payload:
        first_line = output_payload.splitlines()[0][:120]
        print(f"       output={first_line}")

    error_message = (s.get("error_message") or "").strip()
    if error_message:
        print(f"       error={error_message[:120]}")
PY
}

get_task_status() {
  local task_id="$1"
  fetch_tasks
  python3 - "$TMP_TASKS_FILE" "$task_id" <<'PY'
import json, sys

path = sys.argv[1]
task_id = sys.argv[2]

try:
    raw = open(path, "r", encoding="utf-8").read().strip()
except Exception:
    print("")
    raise SystemExit(0)

if not raw:
    print("")
    raise SystemExit(0)

try:
    tasks = json.loads(raw)
except Exception:
    print("")
    raise SystemExit(0)

for t in tasks:
    if str(t.get("id")) == str(task_id):
        print(t.get("status", ""))
        raise SystemExit(0)

print("")
PY
}

main() {
  local task_id="${1:-}"

  if [[ -z "$task_id" ]]; then
    task_id="$(get_latest_task_id)"
  fi

  if [[ -z "$task_id" ]]; then
    echo "没有可观察的任务"
    exit 1
  fi

  while true; do
    # clear || true
    echo "== task_watch =="
    echo "API: ${API_BASE}"
    echo "刷新间隔: ${REFRESH_SECONDS}s"
    echo ""

    print_task_header "$task_id"
    print_task_steps "$task_id"

    local status
    status="$(get_task_status "$task_id")"

    if [[ "$status" == "completed" || "$status" == "failed" ]]; then
      echo ""
      echo "任务已结束，状态: $status"
      exit 0
    fi

    sleep "$REFRESH_SECONDS"
  done
}

main "$@"