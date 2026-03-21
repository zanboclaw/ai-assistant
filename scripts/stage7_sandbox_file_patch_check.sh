#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-${ROOT_DIR}/logs}"
API_BASE="${API_BASE:-http://127.0.0.1:8000}"
SANDBOX_HOST_ROOT="${SANDBOX_HOST_ROOT:-${ROOT_DIR}/apps/api/stage7_sandbox}"
mkdir -p "$LOG_DIR"
source "${ROOT_DIR}/scripts/http_fallback.sh"

TS="$(date +%F_%H%M%S)"
LOG_FILE="${LOG_DIR}/stage7_sandbox_file_patch_check_${TS}.log"
SOURCE_PATH="scripts/assistant_cli.py"
SOURCE_FILE="${ROOT_DIR}/${SOURCE_PATH}"
TARGET_KEY="smoke/stage7_sandbox_source_patch_${TS}.py"
SANDBOX_FILE="${SANDBOX_HOST_ROOT}/${TARGET_KEY}"
EXPECTED_CONTENT="$(python3 - <<'PY' "$SOURCE_FILE" "$TS"
from pathlib import Path
import sys

content = Path(sys.argv[1]).read_text(encoding="utf-8").rstrip("\n")
print(f"{content}\n\n# stage7 sandbox source patch {sys.argv[2]}\n")
PY
)"

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0

log() {
  echo "[$(date '+%F %T')] $*" | tee -a "$LOG_FILE"
}

section() {
  echo | tee -a "$LOG_FILE"
  echo "========== $* ==========" | tee -a "$LOG_FILE"
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

extract_json_field() {
  local field="$1"
  python3 -c 'import json, sys
data = json.load(sys.stdin)
value = data
for part in sys.argv[1].split("."):
    if isinstance(value, dict):
        value = value.get(part)
    else:
        value = None
        break
print(json.dumps(value, ensure_ascii=False))' "$field"
}

cleanup() {
  if [[ -f "$SANDBOX_FILE" ]]; then
    rm -f "$SANDBOX_FILE"
  fi
}
trap cleanup EXIT

section "Init DB"
api_request POST "/init-db" "" "local_admin" >/dev/null
pass "数据库初始化成功"

section "Reject Invalid Patch"
invalid_resp="$(python3 - <<'PY' "$TARGET_KEY" "$SOURCE_PATH" | api_request_stdin_with_status POST "/change-requests" "local_admin"
import json, sys
target_key, source_path = sys.argv[1:3]
print(json.dumps({
    "target_type": "sandbox_file",
    "target_key": target_key,
    "proposed_payload": {
        "source_path": source_path,
        "patch": "@@ -1,1 +1,1 @@\n-not a real line\n+#!/usr/bin/env python3\n",
    },
    "rationale": "invalid patch should fail"
}, ensure_ascii=False))
PY
)"
invalid_status="$(printf '%s' "$invalid_resp" | sed -n '1p')"
invalid_body="$(printf '%s' "$invalid_resp" | sed '1d')"
if [[ "$invalid_status" == "400" ]]; then
  if printf '%s' "$invalid_body" | grep -Eq 'context mismatch|removal mismatch|invalid hunk|unified diff'; then
    pass "非法 unified diff 会被 API 拒绝"
  else
    fail "非法 unified diff 的报错信息异常: ${invalid_body}"
  fi
else
  fail "非法 unified diff 未返回预期 400: ${invalid_resp}"
fi

section "Prepare Source Snapshot"
read -r SOURCE_HASH SOURCE_SIZE < <(python3 - <<'PY' "$SOURCE_FILE"
from pathlib import Path
import hashlib
import sys

raw = Path(sys.argv[1]).read_bytes()
print(hashlib.sha256(raw).hexdigest(), len(raw))
PY
)
if [[ -n "$EXPECTED_CONTENT" && "$SOURCE_HASH" =~ ^[0-9a-f]{64}$ && "$SOURCE_SIZE" =~ ^[1-9][0-9]*$ ]]; then
  pass "已读取 patch source_path=${SOURCE_PATH}"
else
  fail "patch source snapshot 读取失败: ${SOURCE_PATH}"
fi

section "Create Sandbox File Patch Change Request"
change_resp="$(python3 - <<'PY' "$TARGET_KEY" "$SOURCE_PATH" "$SOURCE_FILE" "$TS" | api_request_stdin POST "/change-requests" "local_admin"
import difflib
import json
from pathlib import Path
import sys

target_key, source_path, source_file, ts = sys.argv[1:5]
source_content = Path(source_file).read_text(encoding="utf-8")
patched_content = source_content.rstrip("\n") + f"\n\n# stage7 sandbox source patch {ts}\n"
patch_text = "".join(difflib.unified_diff(
    source_content.splitlines(keepends=True),
    patched_content.splitlines(keepends=True),
    fromfile=f"a/{source_path}",
    tofile=f"b/{source_path}",
))
print(json.dumps({
    "target_type": "sandbox_file",
    "target_key": target_key,
    "proposed_payload": {
        "source_path": source_path,
        "patch": patch_text,
    },
    "rationale": "stage7 sandbox file source-patch smoke"
}, ensure_ascii=False))
PY
)"
change_request_id="$(printf '%s' "$change_resp" | extract_json_field "id" | tr -d '"')"
change_target_type="$(printf '%s' "$change_resp" | extract_json_field "target_type" | tr -d '"')"
baseline_exists="$(printf '%s' "$change_resp" | extract_json_field "baseline_payload.exists" | tr -d '"')"
patch_summary="$(printf '%s' "$change_resp" | extract_json_field "patch_summary" | tr -d '"')"
patch_format="$(printf '%s' "$change_resp" | extract_json_field "payload_patch.format" | tr -d '"')"
patch_changed_key_count="$(printf '%s' "$change_resp" | extract_json_field "payload_patch.changed_key_count" | tr -d '"')"
source_copy_path="$(printf '%s' "$change_resp" | extract_json_field "proposed_payload.source_copy.source_path" | tr -d '"')"
source_copy_kind="$(printf '%s' "$change_resp" | extract_json_field "proposed_payload.source_copy.source_kind" | tr -d '"')"
source_copy_hash="$(printf '%s' "$change_resp" | extract_json_field "proposed_payload.source_copy.source_hash" | tr -d '"')"
content_matches_source="$(printf '%s' "$change_resp" | extract_json_field "proposed_payload.source_copy.content_matches_source" | tr -d '"')"
source_copy_size="$(printf '%s' "$change_resp" | extract_json_field "proposed_payload.source_copy.source_size_bytes" | tr -d '"')"
patch_input_format="$(printf '%s' "$change_resp" | extract_json_field "proposed_payload.patch_input.format" | tr -d '"')"
patch_input_size="$(printf '%s' "$change_resp" | extract_json_field "proposed_payload.patch_input.input_size_bytes" | tr -d '"')"
patch_input_line_count="$(printf '%s' "$change_resp" | extract_json_field "proposed_payload.patch_input.line_count" | tr -d '"')"
patch_applied_format="$(printf '%s' "$change_resp" | extract_json_field "proposed_payload.patch_applied.format" | tr -d '"')"
patch_applied_base_kind="$(printf '%s' "$change_resp" | extract_json_field "proposed_payload.patch_applied.base_kind" | tr -d '"')"
patch_applied_hunk_count="$(printf '%s' "$change_resp" | extract_json_field "proposed_payload.patch_applied.hunk_count" | tr -d '"')"
patch_applied_added_line_count="$(printf '%s' "$change_resp" | extract_json_field "proposed_payload.patch_applied.added_line_count" | tr -d '"')"
patch_applied_removed_line_count="$(printf '%s' "$change_resp" | extract_json_field "proposed_payload.patch_applied.removed_line_count" | tr -d '"')"
patch_applied_content_changed="$(printf '%s' "$change_resp" | extract_json_field "proposed_payload.patch_applied.content_changed" | tr -d '"')"
if [[ "$change_request_id" =~ ^[0-9]+$ && "$change_target_type" == "sandbox_file" ]]; then
  pass "成功创建 sandbox_file source-patch 变更单 #${change_request_id}"
else
  fail "创建 sandbox_file source-patch 变更单失败: ${change_resp}"
fi
if [[ "$baseline_exists" == "false" && -n "$patch_summary" && "$patch_format" == "json_object_diff_v1" && "$patch_changed_key_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "sandbox_file source-patch 变更单已暴露 patch artifact，且基线文件为空"
else
  fail "sandbox_file source-patch patch artifact 字段异常: ${change_resp}"
fi
if [[ "$source_copy_path" == "$SOURCE_PATH" && "$source_copy_kind" == "workspace_file" && "$source_copy_hash" == "$SOURCE_HASH" && "$content_matches_source" == "false" && "$source_copy_size" == "$SOURCE_SIZE" ]]; then
  pass "sandbox_file source-patch 变更单已记录 source-copy 元数据"
else
  fail "sandbox_file source-patch source-copy 元数据异常: ${change_resp}"
fi
if [[ "$patch_input_format" == "unified_diff" && "$patch_input_size" =~ ^[1-9][0-9]*$ && "$patch_input_line_count" =~ ^[1-9][0-9]*$ && "$patch_applied_format" == "unified_diff" && "$patch_applied_base_kind" == "source_copy" && "$patch_applied_hunk_count" =~ ^[1-9][0-9]*$ && "$patch_applied_added_line_count" =~ ^[1-9][0-9]*$ && "$patch_applied_removed_line_count" =~ ^[0-9]+$ && "$patch_applied_content_changed" == "true" ]]; then
  pass "sandbox_file source-patch 变更单已记录 patch 输入与应用元数据"
else
  fail "sandbox_file source-patch patch 元数据异常: ${change_resp}"
fi

section "Approve And Apply Change Request"
approve_resp="$(api_request POST "/change-requests/${change_request_id}/approve" '{"note":"sandbox source patch approve"}' "local_admin")"
approve_status="$(printf '%s' "$approve_resp" | extract_json_field "status" | tr -d '"')"
if [[ "$approve_status" == "approved" ]]; then
  pass "sandbox_file source-patch 变更单已批准"
else
  fail "sandbox_file source-patch 变更单批准失败: ${approve_resp}"
fi

apply_resp="$(api_request POST "/change-requests/${change_request_id}/apply" "" "local_admin")"
apply_status="$(printf '%s' "$apply_resp" | extract_json_field "status" | tr -d '"')"
rollback_ready="$(printf '%s' "$apply_resp" | extract_json_field "rollback_ready" | tr -d '"')"
rollback_exists="$(printf '%s' "$apply_resp" | extract_json_field "rollback_payload.exists" | tr -d '"')"
if [[ "$apply_status" == "applied" ]]; then
  pass "sandbox_file source-patch 变更单已应用"
else
  fail "sandbox_file source-patch 变更单应用失败: ${apply_resp}"
fi
if [[ "$rollback_ready" == "true" && "$rollback_exists" == "false" ]]; then
  pass "应用后已捕获 sandbox_file source-patch rollback artifact"
else
  fail "sandbox_file source-patch rollback artifact 异常: ${apply_resp}"
fi

section "Verify Sandbox File State"
if [[ -f "$SANDBOX_FILE" ]]; then
  actual_content="$(cat "$SANDBOX_FILE")"
  if [[ "$actual_content"$'\n' == "$EXPECTED_CONTENT" || "$actual_content" == "$EXPECTED_CONTENT" ]]; then
    pass "sandbox_file source-patch 已写入宿主目录且内容正确"
  else
    fail "sandbox_file source-patch 内容不一致: ${SANDBOX_FILE}"
  fi
else
  fail "sandbox_file source-patch 未写入宿主目录: ${SANDBOX_FILE}"
fi

overview_resp="$(api_request GET "/monitor/overview")"
sandbox_file_applied_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.sandbox_file_applied_count" | tr -d '"')"
sandbox_source_copy_applied_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.sandbox_source_copy_applied_count" | tr -d '"')"
sandbox_source_patch_applied_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.sandbox_source_patch_applied_count" | tr -d '"')"
if [[ "$sandbox_file_applied_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "monitor/overview 已暴露 sandbox_file_applied_count=${sandbox_file_applied_count}"
else
  fail "monitor/overview 未返回 sandbox_file_applied_count: ${overview_resp}"
fi
if [[ "$sandbox_source_copy_applied_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "monitor/overview 已暴露 sandbox_source_copy_applied_count=${sandbox_source_copy_applied_count}"
else
  fail "monitor/overview 未返回 sandbox_source_copy_applied_count: ${overview_resp}"
fi
if [[ "$sandbox_source_patch_applied_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "monitor/overview 已暴露 sandbox_source_patch_applied_count=${sandbox_source_patch_applied_count}"
else
  fail "monitor/overview 未返回 sandbox_source_patch_applied_count: ${overview_resp}"
fi

section "Verify Rollback Draft"
draft_resp="$(api_request GET "/change-requests/${change_request_id}/rollback-draft" "" "local_admin")"
draft_ready="$(printf '%s' "$draft_resp" | extract_json_field "rollback_ready" | tr -d '"')"
draft_kind="$(printf '%s' "$draft_resp" | extract_json_field "proposal_kind" | tr -d '"')"
draft_exists="$(printf '%s' "$draft_resp" | extract_json_field "proposed_payload.exists" | tr -d '"')"
draft_patch_format="$(printf '%s' "$draft_resp" | extract_json_field "payload_patch.format" | tr -d '"')"
draft_patch_changed_key_count="$(printf '%s' "$draft_resp" | extract_json_field "payload_patch.changed_key_count" | tr -d '"')"
if [[ "$draft_ready" == "true" && "$draft_kind" == "rollback" && "$draft_exists" == "false" ]]; then
  pass "sandbox_file source-patch rollback draft 可用，且会恢复为不存在"
else
  fail "sandbox_file source-patch rollback draft 异常: ${draft_resp}"
fi
if [[ "$draft_patch_format" == "json_object_diff_v1" && "$draft_patch_changed_key_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "sandbox_file source-patch rollback draft 已暴露 patch artifact"
else
  fail "sandbox_file source-patch rollback draft patch artifact 异常: ${draft_resp}"
fi

section "Create And Apply Rollback Change Request"
rollback_create_resp="$(api_request POST "/change-requests/${change_request_id}/rollback" "" "local_admin")"
rollback_change_id="$(printf '%s' "$rollback_create_resp" | extract_json_field "change_request.id" | tr -d '"')"
rollback_kind="$(printf '%s' "$rollback_create_resp" | extract_json_field "change_request.proposal_kind" | tr -d '"')"
rollback_source_id="$(printf '%s' "$rollback_create_resp" | extract_json_field "change_request.source_change_request_id" | tr -d '"')"
if [[ "$rollback_change_id" =~ ^[0-9]+$ && "$rollback_kind" == "rollback" && "$rollback_source_id" == "$change_request_id" ]]; then
  pass "sandbox_file source-patch 回滚变更单创建成功 #${rollback_change_id}"
else
  fail "sandbox_file source-patch 回滚变更单创建失败: ${rollback_create_resp}"
fi

rollback_approve_resp="$(api_request POST "/change-requests/${rollback_change_id}/approve" '{"note":"sandbox source patch rollback approve"}' "local_admin")"
rollback_approve_status="$(printf '%s' "$rollback_approve_resp" | extract_json_field "status" | tr -d '"')"
if [[ "$rollback_approve_status" == "approved" ]]; then
  pass "sandbox_file source-patch 回滚变更单已批准"
else
  fail "sandbox_file source-patch 回滚变更单批准失败: ${rollback_approve_resp}"
fi

rollback_apply_resp="$(api_request POST "/change-requests/${rollback_change_id}/apply" "" "local_admin")"
rollback_apply_status="$(printf '%s' "$rollback_apply_resp" | extract_json_field "status" | tr -d '"')"
if [[ "$rollback_apply_status" == "applied" ]]; then
  pass "sandbox_file source-patch 回滚变更单已应用"
else
  fail "sandbox_file source-patch 回滚变更单应用失败: ${rollback_apply_resp}"
fi

section "Verify Sandbox File Restored"
if [[ ! -e "$SANDBOX_FILE" ]]; then
  pass "sandbox_file source-patch 已恢复到基线状态（文件不存在）"
else
  fail "sandbox_file source-patch 未恢复到基线状态: ${SANDBOX_FILE}"
fi

audit_resp="$(api_request GET "/audit-logs?event_type=change_request.rollback_create&limit=20")"
audit_match="$(printf '%s' "$audit_resp" | python3 -c 'import json,sys
source_id=int(sys.argv[1]); rollback_id=int(sys.argv[2]); data=json.load(sys.stdin)
print(any(int((item.get("details") or {}).get("source_change_request_id") or 0)==source_id and int((item.get("details") or {}).get("rollback_change_request_id") or 0)==rollback_id for item in data))' "$change_request_id" "$rollback_change_id")"
if [[ "$audit_match" == "True" ]]; then
  pass "audit log 记录了 sandbox_file source-patch rollback create"
else
  fail "audit log 未记录 sandbox_file source-patch rollback create: ${audit_resp}"
fi

section "Done"
log "target_key: ${TARGET_KEY}"
log "source_path: ${SOURCE_PATH}"
log "日志文件: $LOG_FILE"
log "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT} WARN=${WARN_COUNT}"

if (( FAIL_COUNT > 0 )); then
  exit 1
fi
