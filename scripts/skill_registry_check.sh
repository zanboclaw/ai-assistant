#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_BASE="${API_BASE:-http://localhost:8000}"
ACTOR_NAME="${ACTOR_NAME:-local_admin}"
SOURCE_PATH="${SOURCE_PATH:-skills/workspace_file_summary.skill.json}"
TARGET_FILE="${TARGET_FILE:-/workspace/skill_summary_output.md}"

auto_approve_pending_approvals() {
  local task_id="$1"
  local approval_ids
  approval_ids="$(
    curl -sS -H "X-Actor-Name: ${ACTOR_NAME}" "${API_BASE}/tasks/${task_id}/approvals" | python3 -c '
import json, sys
rows = json.load(sys.stdin)
for row in rows:
    if row.get("status") == "pending":
        print(row.get("id"))
'
  )"

  if [[ -z "${approval_ids}" ]]; then
    return 0
  fi

  while IFS= read -r approval_id; do
    [[ -z "${approval_id}" ]] && continue
    curl -sS -X POST "${API_BASE}/approvals/${approval_id}/approve" \
      -H "Content-Type: application/json" \
      -H "X-Actor-Name: ${ACTOR_NAME}" \
      -d '{"note":"skill registry smoke auto approve"}'
    echo
  done <<< "${approval_ids}"
}

echo "== Import skill package =="
curl -sS -X POST "${API_BASE}/skills/import" \
  -H "Content-Type: application/json" \
  -H "X-Actor-Name: ${ACTOR_NAME}" \
  -d "{\"source_path\":\"${SOURCE_PATH}\",\"activate\":true}" >/tmp/skill_import.json
cat /tmp/skill_import.json

echo
echo "== Verify skill list =="
curl -sS -H "X-Actor-Name: ${ACTOR_NAME}" "${API_BASE}/skills" > /tmp/skills_list.json
python3 - <<'PY'
import json
from pathlib import Path
items = json.loads(Path('/tmp/skills_list.json').read_text())
skill = next((item for item in items if item["skill_id"] == "workspace_file_summary"), None)
assert skill, "workspace_file_summary not found"
assert skill["latest_version"] == "1.0.0", skill
print(json.dumps(skill, ensure_ascii=False, indent=2))
PY

echo
echo "== Create explicit skill task =="
curl -sS -X POST "${API_BASE}/tasks" \
  -H "Content-Type: application/json" \
  -H "X-Actor-Name: ${ACTOR_NAME}" \
  -d "{
    \"user_input\":\"请按 skill 执行一次文件摘要\",
    \"skill_id\":\"workspace_file_summary\",
    \"skill_args\":{
      \"source_path\":\"/workspace/test_note.txt\",
      \"output_path\":\"${TARGET_FILE}\"
    }
  }" >/tmp/skill_task_create.json
cat /tmp/skill_task_create.json

TASK_ID="$(python3 - <<'PY'
import json
from pathlib import Path
print(json.loads(Path('/tmp/skill_task_create.json').read_text())['id'])
PY
)"

echo
echo "== Wait task complete =="
for _ in $(seq 1 60); do
  STATUS="$(curl -sS "${API_BASE}/tasks/${TASK_ID}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
  echo "task=${TASK_ID} status=${STATUS}"
  if [ "${STATUS}" = "waiting_approval" ]; then
    auto_approve_pending_approvals "${TASK_ID}"
  fi
  if [ "${STATUS}" = "completed" ]; then
    break
  fi
  sleep 2
done

if [ "${STATUS}" != "completed" ]; then
  echo "skill task did not complete"
  exit 1
fi

echo
echo "== Verify output file =="
test -f "${ROOT_DIR}/data/workspace/$(basename "${TARGET_FILE}")"
cat "${ROOT_DIR}/data/workspace/$(basename "${TARGET_FILE}")"

echo
echo "== Verify skill traces =="
curl -sS "${API_BASE}/tasks/${TASK_ID}/traces" > /tmp/skill_task_traces.json
python3 - <<'PY'
import json
from pathlib import Path
payload = json.loads(Path('/tmp/skill_task_traces.json').read_text())
skill_traces = payload.get("skill_traces") or []
assert skill_traces, payload
assert skill_traces[0]["skill_id"] == "workspace_file_summary", skill_traces[0]
metadata = skill_traces[0].get("metadata_json") or {}
output_snapshot = skill_traces[0].get("output_snapshot") or {}
assert "source_path" in (metadata.get("arg_keys") or []), metadata
assert "output_path" in (metadata.get("arg_keys") or []), metadata
assert output_snapshot.get("step_count") == 3, output_snapshot
assert len(output_snapshot.get("step_titles") or []) == 3, output_snapshot
print(json.dumps({
    "task_id": payload["task_id"],
    "skill_traces": len(skill_traces),
    "plan_source": (payload.get("task_trace") or {}).get("plan_source"),
    "skill_arg_keys": metadata.get("arg_keys") or [],
    "planned_step_count": output_snapshot.get("step_count"),
}, ensure_ascii=False, indent=2))
PY

echo
echo "PASS: Skill registry smoke completed"
