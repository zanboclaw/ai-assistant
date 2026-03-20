#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-${ROOT_DIR}/logs}"
API_BASE="${API_BASE:-http://127.0.0.1:8000}"
SANDBOX_HOST_ROOT="${SANDBOX_HOST_ROOT:-${ROOT_DIR}/apps/api/stage7_sandbox}"
mkdir -p "$LOG_DIR"
source "${ROOT_DIR}/scripts/http_fallback.sh"

TS="$(date +%F_%H%M%S)"
LOG_FILE="${LOG_DIR}/stage7_sandbox_file_change_check_${TS}.log"
SOURCE_PATH="scripts/stage7_sandbox_file_change_check.sh"
SOURCE_FILE="${ROOT_DIR}/${SOURCE_PATH}"
TARGET_KEY="smoke/stage7_sandbox_source_copy_${TS}.sh"
SANDBOX_FILE="${SANDBOX_HOST_ROOT}/${TARGET_KEY}"

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

section "Create Sandbox File Change Request"
create_payload="$(python3 - <<'PY' "$TARGET_KEY" "$SOURCE_PATH" "$SOURCE_FILE"
import json, pathlib, sys
target_key, source_path, source_file = sys.argv[1:4]
content = pathlib.Path(source_file).read_text(encoding="utf-8")
print(json.dumps({
    "target_type": "sandbox_file",
    "target_key": target_key,
    "proposed_payload": {
        "source_path": source_path,
        "content": content
    },
    "rationale": "stage7 sandbox file source-copy smoke"
}, ensure_ascii=False))
PY
)"
change_resp="$(printf '%s' "$create_payload" | api_request_stdin POST "/change-requests" "local_admin")"
change_request_id="$(printf '%s' "$change_resp" | extract_json_field "id" | tr -d '"')"
change_target_type="$(printf '%s' "$change_resp" | extract_json_field "target_type" | tr -d '"')"
baseline_exists="$(printf '%s' "$change_resp" | extract_json_field "baseline_payload.exists" | tr -d '"')"
patch_summary="$(printf '%s' "$change_resp" | extract_json_field "patch_summary" | tr -d '"')"
patch_format="$(printf '%s' "$change_resp" | extract_json_field "payload_patch.format" | tr -d '"')"
patch_changed_key_count="$(printf '%s' "$change_resp" | extract_json_field "payload_patch.changed_key_count" | tr -d '"')"
source_copy_path="$(printf '%s' "$change_resp" | extract_json_field "proposed_payload.source_copy.source_path" | tr -d '"')"
source_copy_kind="$(printf '%s' "$change_resp" | extract_json_field "proposed_payload.source_copy.source_kind" | tr -d '"')"
content_matches_source="$(printf '%s' "$change_resp" | extract_json_field "proposed_payload.source_copy.content_matches_source" | tr -d '"')"
source_copy_size="$(printf '%s' "$change_resp" | extract_json_field "proposed_payload.source_copy.source_size_bytes" | tr -d '"')"
if [[ "$change_request_id" =~ ^[0-9]+$ && "$change_target_type" == "sandbox_file" ]]; then
  pass "成功创建 sandbox_file 变更单 #${change_request_id}"
else
  fail "创建 sandbox_file 变更单失败: ${change_resp}"
fi
if [[ "$baseline_exists" == "false" && -n "$patch_summary" && "$patch_format" == "json_object_diff_v1" && "$patch_changed_key_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "sandbox_file 变更单已暴露 patch artifact，且基线文件为空"
else
  fail "sandbox_file patch artifact 字段异常: ${change_resp}"
fi
if [[ "$source_copy_path" == "$SOURCE_PATH" && "$source_copy_kind" == "workspace_file" && "$content_matches_source" == "true" && "$source_copy_size" =~ ^[1-9][0-9]*$ ]]; then
  pass "sandbox_file 变更单已记录 source-copy 元数据"
else
  fail "sandbox_file source-copy 元数据异常: ${change_resp}"
fi

section "Approve And Apply Change Request"
approve_resp="$(api_request POST "/change-requests/${change_request_id}/approve" '{"note":"sandbox smoke approve"}' "local_admin")"
approve_status="$(printf '%s' "$approve_resp" | extract_json_field "status" | tr -d '"')"
if [[ "$approve_status" == "approved" ]]; then
  pass "sandbox_file 变更单已批准"
else
  fail "sandbox_file 变更单批准失败: ${approve_resp}"
fi

apply_resp="$(api_request POST "/change-requests/${change_request_id}/apply" "" "local_admin")"
apply_status="$(printf '%s' "$apply_resp" | extract_json_field "status" | tr -d '"')"
rollback_ready="$(printf '%s' "$apply_resp" | extract_json_field "rollback_ready" | tr -d '"')"
rollback_exists="$(printf '%s' "$apply_resp" | extract_json_field "rollback_payload.exists" | tr -d '"')"
if [[ "$apply_status" == "applied" ]]; then
  pass "sandbox_file 变更单已应用"
else
  fail "sandbox_file 变更单应用失败: ${apply_resp}"
fi
if [[ "$rollback_ready" == "true" && "$rollback_exists" == "false" ]]; then
  pass "应用后已捕获 sandbox_file rollback artifact"
else
  fail "sandbox_file rollback artifact 异常: ${apply_resp}"
fi

section "Verify Sandbox File State"
if [[ -f "$SANDBOX_FILE" ]]; then
  if cmp -s "$SANDBOX_FILE" "$SOURCE_FILE"; then
    pass "sandbox_file 已写入宿主目录并与源码副本一致"
  else
    fail "sandbox_file 内容与源码副本不一致: ${SANDBOX_FILE}"
  fi
else
  fail "sandbox_file 未写入宿主目录: ${SANDBOX_FILE}"
fi

overview_resp="$(api_request GET "/monitor/overview")"
sandbox_file_applied_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.sandbox_file_applied_count" | tr -d '"')"
sandbox_source_copy_applied_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.sandbox_source_copy_applied_count" | tr -d '"')"
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

section "Verify Rollback Draft"
draft_resp="$(api_request GET "/change-requests/${change_request_id}/rollback-draft" "" "local_admin")"
draft_ready="$(printf '%s' "$draft_resp" | extract_json_field "rollback_ready" | tr -d '"')"
draft_kind="$(printf '%s' "$draft_resp" | extract_json_field "proposal_kind" | tr -d '"')"
draft_exists="$(printf '%s' "$draft_resp" | extract_json_field "proposed_payload.exists" | tr -d '"')"
draft_patch_format="$(printf '%s' "$draft_resp" | extract_json_field "payload_patch.format" | tr -d '"')"
draft_patch_changed_key_count="$(printf '%s' "$draft_resp" | extract_json_field "payload_patch.changed_key_count" | tr -d '"')"
if [[ "$draft_ready" == "true" && "$draft_kind" == "rollback" && "$draft_exists" == "false" ]]; then
  pass "sandbox_file rollback draft 可用，且会恢复为不存在"
else
  fail "sandbox_file rollback draft 异常: ${draft_resp}"
fi
if [[ "$draft_patch_format" == "json_object_diff_v1" && "$draft_patch_changed_key_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "sandbox_file rollback draft 已暴露 patch artifact"
else
  fail "sandbox_file rollback draft patch artifact 异常: ${draft_resp}"
fi

section "Create And Apply Rollback Change Request"
rollback_create_resp="$(api_request POST "/change-requests/${change_request_id}/rollback" "" "local_admin")"
rollback_change_id="$(printf '%s' "$rollback_create_resp" | extract_json_field "change_request.id" | tr -d '"')"
rollback_kind="$(printf '%s' "$rollback_create_resp" | extract_json_field "change_request.proposal_kind" | tr -d '"')"
rollback_source_id="$(printf '%s' "$rollback_create_resp" | extract_json_field "change_request.source_change_request_id" | tr -d '"')"
if [[ "$rollback_change_id" =~ ^[0-9]+$ && "$rollback_kind" == "rollback" && "$rollback_source_id" == "$change_request_id" ]]; then
  pass "sandbox_file 回滚变更单创建成功 #${rollback_change_id}"
else
  fail "sandbox_file 回滚变更单创建失败: ${rollback_create_resp}"
fi

rollback_approve_resp="$(api_request POST "/change-requests/${rollback_change_id}/approve" '{"note":"sandbox rollback approve"}' "local_admin")"
rollback_approve_status="$(printf '%s' "$rollback_approve_resp" | extract_json_field "status" | tr -d '"')"
if [[ "$rollback_approve_status" == "approved" ]]; then
  pass "sandbox_file 回滚变更单已批准"
else
  fail "sandbox_file 回滚变更单批准失败: ${rollback_approve_resp}"
fi

rollback_apply_resp="$(api_request POST "/change-requests/${rollback_change_id}/apply" "" "local_admin")"
rollback_apply_status="$(printf '%s' "$rollback_apply_resp" | extract_json_field "status" | tr -d '"')"
if [[ "$rollback_apply_status" == "applied" ]]; then
  pass "sandbox_file 回滚变更单已应用"
else
  fail "sandbox_file 回滚变更单应用失败: ${rollback_apply_resp}"
fi

section "Verify Sandbox File Restored"
if [[ ! -e "$SANDBOX_FILE" ]]; then
  pass "sandbox_file 已恢复到基线状态（文件不存在）"
else
  fail "sandbox_file 未恢复到基线状态: ${SANDBOX_FILE}"
fi

audit_resp="$(api_request GET "/audit-logs?event_type=change_request.rollback_create&limit=20")"
audit_match="$(printf '%s' "$audit_resp" | python3 -c 'import json,sys
source_id=int(sys.argv[1]); rollback_id=int(sys.argv[2]); data=json.load(sys.stdin)
print(any(int((item.get("details") or {}).get("source_change_request_id") or 0)==source_id and int((item.get("details") or {}).get("rollback_change_request_id") or 0)==rollback_id for item in data))' "$change_request_id" "$rollback_change_id")"
if [[ "$audit_match" == "True" ]]; then
  pass "audit log 记录了 sandbox_file rollback create"
else
  fail "audit log 未记录 sandbox_file rollback create: ${audit_resp}"
fi

section "Done"
log "target_key: ${TARGET_KEY}"
log "source_path: ${SOURCE_PATH}"
log "日志文件: $LOG_FILE"
log "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT} WARN=${WARN_COUNT}"

if (( FAIL_COUNT > 0 )); then
  exit 1
fi
