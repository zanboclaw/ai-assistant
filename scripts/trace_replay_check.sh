#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_BASE="${API_BASE:-http://localhost:8000}"
ACTOR_NAME="${ACTOR_NAME:-local_admin}"

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
      -d '{"note":"trace replay smoke auto approve"}' >/tmp/trace_replay_approve.json
    cat /tmp/trace_replay_approve.json
    echo
  done <<< "${approval_ids}"
}

echo "== Create replay probe task =="
curl -sS -X POST "${API_BASE}/tasks" \
  -H "Content-Type: application/json" \
  -H "X-Actor-Name: ${ACTOR_NAME}" \
  -d '{"user_input":"读取文件 /workspace/test_note.txt 并整理要点后写入 /workspace/p0_trace_report_v2.md"}' >/tmp/trace_replay_task.json
cat /tmp/trace_replay_task.json

TASK_ID="$(python3 - <<'PY'
import json
from pathlib import Path
print(json.loads(Path('/tmp/trace_replay_task.json').read_text())['id'])
PY
)"

echo
echo "== Wait task complete =="
for _ in $(seq 1 60); do
  STATUS="$(curl -sS "${API_BASE}/tasks/${TASK_ID}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
  echo "task=${TASK_ID} status=${STATUS}"
  if [[ "${STATUS}" == "waiting_approval" ]]; then
    auto_approve_pending_approvals "${TASK_ID}"
  fi
  if [[ "${STATUS}" == "completed" ]]; then
    break
  fi
  sleep 2
done

if [[ "${STATUS}" != "completed" ]]; then
  echo "trace replay task did not complete"
  exit 1
fi

echo
echo "== Verify replay payload =="
curl -sS "${API_BASE}/tasks/${TASK_ID}/replay" >/tmp/trace_replay_payload.json
python3 - <<'PY'
import json
from pathlib import Path
payload = json.loads(Path('/tmp/trace_replay_payload.json').read_text())
summary = payload.get("summary") or {}
steps = payload.get("steps") or []
assert payload.get("task", {}).get("id"), payload
assert summary.get("mode") == "read_only_trace_replay_v1", summary
assert len(steps) >= 2, steps
assert steps[0].get("trace_counts", {}).get("step", 0) >= 1, steps[0]
assert "input_payload" in steps[0], steps[0]
print(json.dumps({
    "task_id": payload["task"]["id"],
    "plan_source": summary.get("plan_source"),
    "step_count": summary.get("step_count"),
    "trace_counts_first_step": steps[0].get("trace_counts"),
}, ensure_ascii=False, indent=2))
PY

echo
echo "PASS: Trace replay smoke completed"
