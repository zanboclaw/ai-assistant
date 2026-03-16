#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8000}"

resp="$(curl -s "${API_BASE}/tasks")"

JSON_PAYLOAD="$resp" python3 - <<'PY'
import json
import os
import sys

raw = os.environ.get("JSON_PAYLOAD", "").strip()
if not raw:
    print("ERROR: /tasks 返回为空")
    sys.exit(1)

try:
    tasks = json.loads(raw)
except Exception as e:
    print(f"ERROR: /tasks 返回不是合法 JSON: {e}")
    sys.exit(1)

if not isinstance(tasks, list) or not tasks:
    print("暂无任务")
    sys.exit(0)

t = tasks[0]

print("===== 最新任务 =====")
print(f"id           : {t.get('id')}")
print(f"status       : {t.get('status')}")
print(f"user_input   : {t.get('user_input')}")
print(f"error_message: {t.get('error_message')}")
print("result:")
print(t.get("result"))
PY