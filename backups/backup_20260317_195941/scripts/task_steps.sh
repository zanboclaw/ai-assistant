#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8000}"
TASK_ID="${1:-}"
TMP_TASKS_FILE="$(mktemp)"
TMP_STEPS_FILE="$(mktemp)"

cleanup() {
  rm -f "$TMP_TASKS_FILE" "$TMP_STEPS_FILE"
}
trap cleanup EXIT

get_latest_task_id() {
  curl -s "${API_BASE}/tasks" > "$TMP_TASKS_FILE"

  python3 - "$TMP_TASKS_FILE" <<'PY'
import json
import sys

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

if [[ -z "$TASK_ID" ]]; then
  TASK_ID="$(get_latest_task_id)"
fi

if [[ -z "$TASK_ID" ]]; then
  echo "没有可查看的任务"
  exit 1
fi

curl -s "${API_BASE}/tasks/${TASK_ID}/steps" > "$TMP_STEPS_FILE"

python3 - "$TMP_STEPS_FILE" "$TASK_ID" <<'PY'
import json
import sys

path = sys.argv[1]
task_id = sys.argv[2]

try:
    raw = open(path, "r", encoding="utf-8").read().strip()
except Exception:
    print(f"读取任务 {task_id} 的 steps 失败")
    raise SystemExit(1)

if not raw:
    print(f"任务 {task_id} 的 steps 为空")
    raise SystemExit(1)

try:
    steps = json.loads(raw)
except Exception as e:
    print(f"任务 {task_id} 的 steps JSON 解析失败: {e}")
    raise SystemExit(1)

if not isinstance(steps, list) or not steps:
    print(f"任务 {task_id} 暂无 steps")
    raise SystemExit(0)

print(f"任务ID: {task_id}")
print("")

for s in steps:
    step_order = s.get("step_order")
    step_name = s.get("step_name")
    tool_name = s.get("tool_name")
    status = s.get("status")
    input_payload = (s.get("input_payload") or "").strip()
    output_payload = (s.get("output_payload") or "").strip()
    error_message = (s.get("error_message") or "").strip()

    print(f"[{step_order}] {step_name}")
    print(f"  tool:   {tool_name}")
    print(f"  status: {status}")

    if input_payload:
        print(f"  input:  {input_payload[:220]}")

    if output_payload:
        first_line = output_payload.splitlines()[0][:220]
        print(f"  output: {first_line}")

    if error_message:
        print(f"  error:  {error_message[:220]}")

    print("")
PY