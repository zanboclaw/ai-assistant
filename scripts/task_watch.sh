#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8000}"
TASK_ID="${1:-}"
INTERVAL="${INTERVAL:-2}"

get_latest_task_id() {
  local resp
  resp="$(curl -s "${API_BASE}/tasks")"

  JSON_PAYLOAD="$resp" python3 - <<'PY'
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
}

get_task_summary() {
  local task_id="$1"
  local resp
  resp="$(curl -s "${API_BASE}/tasks")"

  JSON_PAYLOAD="$resp" TARGET_TASK_ID="$task_id" python3 - <<'PY'
import json
import os
import sys

raw = os.environ.get("JSON_PAYLOAD", "").strip()
target_id = os.environ.get("TARGET_TASK_ID", "").strip()

if not raw or not target_id:
    sys.exit(1)

tasks = json.loads(raw)
target = None
for t in tasks:
    if str(t.get("id")) == target_id:
        target = t
        break

if not target:
    sys.exit(2)

print(f"id={target.get('id')}")
print(f"status={target.get('status')}")
print(f"user_input={target.get('user_input')}")
print(f"error_message={target.get('error_message')}")
print("result:")
print(target.get("result"))
PY
}

get_task_status_only() {
  local task_id="$1"
  local resp
  resp="$(curl -s "${API_BASE}/tasks")"

  JSON_PAYLOAD="$resp" TARGET_TASK_ID="$task_id" python3 - <<'PY'
import json
import os
import sys

raw = os.environ.get("JSON_PAYLOAD", "").strip()
target_id = os.environ.get("TARGET_TASK_ID", "").strip()

if not raw or not target_id:
    print("")
    sys.exit(0)

try:
    tasks = json.loads(raw)
except Exception:
    print("")
    sys.exit(0)

for t in tasks:
    if str(t.get("id")) == target_id:
        print(t.get("status", ""))
        sys.exit(0)

print("")
PY
}

if [[ -z "${TASK_ID}" ]]; then
  TASK_ID="$(get_latest_task_id)"
fi

if [[ -z "${TASK_ID}" ]]; then
  echo "ERROR: 未获取到任务 ID"
  echo "用法: $0 <task_id>"
  exit 1
fi

echo "开始监控任务: ${TASK_ID}"
echo "轮询间隔: ${INTERVAL}s"
echo

last_status=""

while true; do
  status="$(get_task_status_only "${TASK_ID}")"

  if [[ -z "${status}" ]]; then
    echo "任务 ${TASK_ID} 未找到，继续等待..."
    sleep "${INTERVAL}"
    continue
  fi

  if [[ "${status}" != "${last_status}" ]]; then
    echo "[$(date '+%F %T')] task_id=${TASK_ID} status=${status}"
    last_status="${status}"
  fi

  if [[ "${status}" == "completed" || "${status}" == "failed" ]]; then
    echo
    echo "===== 最终任务结果 ====="
    get_task_summary "${TASK_ID}" || true
    echo
    echo "===== 步骤摘要 ====="
    /opt/ai-assistant/scripts/task_steps.sh "${TASK_ID}" || true
    break
  fi

  sleep "${INTERVAL}"
done