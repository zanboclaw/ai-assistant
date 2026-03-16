#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8000}"
TASK_ID="${1:-}"

if [[ -z "${TASK_ID}" ]]; then
  resp="$(curl -s "${API_BASE}/tasks")"
  TASK_ID="$(JSON_PAYLOAD="$resp" python3 - <<'PY'
import json
import os

raw = os.environ.get("JSON_PAYLOAD", "").strip()
if not raw:
    print("")
    raise SystemExit(0)

try:
    tasks = json.loads(raw)
except Exception:
    print("")
    raise SystemExit(0)

if isinstance(tasks, list) and tasks:
    print(tasks[0].get("id", ""))
else:
    print("")
PY
)"
fi

if [[ -z "${TASK_ID}" ]]; then
  echo "ERROR: 未获取到任务 ID"
  echo "用法: $0 <task_id>"
  exit 1
fi

resp="$(curl -s "${API_BASE}/tasks/${TASK_ID}/steps")"

JSON_PAYLOAD="$resp" python3 - "$TASK_ID" <<'PY'
import json
import os
import sys

task_id = sys.argv[1]
raw = os.environ.get("JSON_PAYLOAD", "").strip()

if not raw:
    print(f"ERROR: /tasks/{task_id}/steps 返回为空")
    sys.exit(1)

try:
    steps = json.loads(raw)
except Exception as e:
    print(f"ERROR: /tasks/{task_id}/steps 返回不是合法 JSON: {e}")
    sys.exit(1)

if not isinstance(steps, list) or not steps:
    print(f"任务 {task_id} 暂无步骤")
    sys.exit(0)

print(f"===== 任务 {task_id} 步骤摘要 =====")
for s in steps:
    print(f"[{s.get('step_order')}] {s.get('step_name')} | status={s.get('status')}")

print()
print(f"===== 任务 {task_id} 步骤详情 =====")
for s in steps:
    print("=" * 72)
    print(f"step_order   : {s.get('step_order')}")
    print(f"step_name    : {s.get('step_name')}")
    print(f"status       : {s.get('status')}")
    print(f"input_payload: {s.get('input_payload')}")
    print("output_payload:")
    print(s.get("output_payload"))
    print(f"error_message: {s.get('error_message')}")
PY