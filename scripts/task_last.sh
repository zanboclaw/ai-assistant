#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8000}"
TMP_FILE="$(mktemp)"

cleanup() {
  rm -f "$TMP_FILE"
}
trap cleanup EXIT

curl -s "${API_BASE}/tasks" > "$TMP_FILE"

python3 - "$TMP_FILE" <<'PY'
import json
import sys

path = sys.argv[1]

try:
    raw = open(path, "r", encoding="utf-8").read().strip()
except Exception:
    print("读取 /tasks 响应失败")
    raise SystemExit(1)

if not raw:
    print("任务列表为空")
    raise SystemExit(1)

try:
    tasks = json.loads(raw)
except Exception as e:
    print(f"任务列表 JSON 解析失败: {e}")
    raise SystemExit(1)

if not isinstance(tasks, list) or not tasks:
    print("没有任务")
    raise SystemExit(1)

t = tasks[0]

print(f"任务ID: {t.get('id')}")
print(f"状态:   {t.get('status')}")
print(f"任务:   {t.get('user_input')}")
if t.get("error_message"):
    print(f"错误:   {t.get('error_message')}")

result = (t.get("result") or "").strip()
if result:
    print("")
    print("结果预览:")
    lines = result.splitlines()
    for line in lines[:12]:
        print(line[:160])
    if len(lines) > 12:
        print("...")
PY