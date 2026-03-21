#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-${ROOT_DIR}/logs}"
API_BASE="${API_BASE:-http://127.0.0.1:8000}"
SANDBOX_HOST_ROOT="${SANDBOX_HOST_ROOT:-${ROOT_DIR}/apps/api/stage7_sandbox}"
mkdir -p "$LOG_DIR"
source "${ROOT_DIR}/scripts/http_fallback.sh"

TS="$(date +%F_%H%M%S)"
LOG_FILE="${LOG_DIR}/stage7_sandbox_file_acceptance_check_${TS}.log"
SOURCE_PATH="scripts/assistant_cli.py"
SOURCE_FILE="${ROOT_DIR}/${SOURCE_PATH}"
ACCEPTANCE_SCRIPT="scripts/stage7_sandbox_file_acceptance_probe.sh"
PASS_TARGET_KEY="smoke/stage7_sandbox_acceptance_pass_${TS}.py"
FAIL_TARGET_KEY="smoke/stage7_sandbox_acceptance_fail_${TS}.py"
PASS_SANDBOX_FILE="${SANDBOX_HOST_ROOT}/${PASS_TARGET_KEY}"
FAIL_SANDBOX_FILE="${SANDBOX_HOST_ROOT}/${FAIL_TARGET_KEY}"
PASS_MARKER="# stage7 sandbox acceptance pass ${TS}"
FAIL_MARKER="# stage7 sandbox acceptance fail ${TS}"
MISSING_MARKER="missing stage7 sandbox acceptance ${TS}"

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
  rm -f "$PASS_SANDBOX_FILE" "$FAIL_SANDBOX_FILE" 2>/dev/null || true
}
trap cleanup EXIT

section "Init DB"
api_request POST "/init-db" "" "local_admin" >/dev/null
pass "数据库初始化成功"

section "Apply Passing Acceptance Change Request"
pass_change_resp="$(python3 - <<'PY' "$PASS_TARGET_KEY" "$SOURCE_PATH" "$SOURCE_FILE" "$PASS_MARKER" "$ACCEPTANCE_SCRIPT" | api_request_stdin POST "/change-requests" "local_admin"
import difflib
import json
from pathlib import Path
import sys

target_key, source_path, source_file, marker, acceptance_script = sys.argv[1:6]
source_content = Path(source_file).read_text(encoding="utf-8")
patched_content = source_content.rstrip("\n") + f"\n\n{marker}\n"
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
        "acceptance": {
            "script_path": acceptance_script,
            "timeout_seconds": 20,
            "env": {
                "STAGE7_EXPECT_CONTAINS": marker,
            },
        },
    },
    "rationale": "stage7 sandbox_file acceptance pass smoke"
}, ensure_ascii=False))
PY
)"
pass_change_request_id="$(printf '%s' "$pass_change_resp" | extract_json_field "id" | tr -d '"')"
pass_acceptance_script="$(printf '%s' "$pass_change_resp" | extract_json_field "proposed_payload.acceptance.script_path" | tr -d '"')"
if [[ "$pass_change_request_id" =~ ^[0-9]+$ && "$pass_acceptance_script" == "$ACCEPTANCE_SCRIPT" ]]; then
  pass "成功创建带 acceptance 的 sandbox_file 变更单 #${pass_change_request_id}"
else
  fail "创建 passing acceptance 变更单失败: ${pass_change_resp}"
fi

pass_approve_resp="$(api_request POST "/change-requests/${pass_change_request_id}/approve" '{"note":"sandbox acceptance pass approve"}' "local_admin")"
pass_approve_status="$(printf '%s' "$pass_approve_resp" | extract_json_field "status" | tr -d '"')"
if [[ "$pass_approve_status" == "approved" ]]; then
  pass "passing acceptance 变更单已批准"
else
  fail "passing acceptance 变更单批准失败: ${pass_approve_resp}"
fi

pass_apply_resp="$(api_request POST "/change-requests/${pass_change_request_id}/apply" "" "local_admin")"
pass_apply_status="$(printf '%s' "$pass_apply_resp" | extract_json_field "status" | tr -d '"')"
pass_acceptance_status="$(printf '%s' "$pass_apply_resp" | extract_json_field "acceptance_status" | tr -d '"')"
pass_acceptance_exit_code="$(printf '%s' "$pass_apply_resp" | extract_json_field "acceptance_report.exit_code" | tr -d '"')"
pass_auto_rollback="$(printf '%s' "$pass_apply_resp" | extract_json_field "auto_rollback_applied" | tr -d '"')"
if [[ "$pass_apply_status" == "applied" && "$pass_acceptance_status" == "passed" && "$pass_acceptance_exit_code" == "0" && "$pass_auto_rollback" == "false" ]]; then
  pass "passing acceptance 变更单应用成功，且 acceptance 已通过"
else
  fail "passing acceptance 应用结果异常: ${pass_apply_resp}"
fi

if [[ -f "$PASS_SANDBOX_FILE" ]] && grep -Fq "$PASS_MARKER" "$PASS_SANDBOX_FILE"; then
  pass "passing acceptance sandbox 文件保留且内容正确"
else
  fail "passing acceptance sandbox 文件状态异常: ${PASS_SANDBOX_FILE}"
fi

section "Apply Failing Acceptance Change Request"
fail_change_resp="$(python3 - <<'PY' "$FAIL_TARGET_KEY" "$SOURCE_PATH" "$SOURCE_FILE" "$FAIL_MARKER" "$ACCEPTANCE_SCRIPT" "$MISSING_MARKER" | api_request_stdin POST "/change-requests" "local_admin"
import difflib
import json
from pathlib import Path
import sys

target_key, source_path, source_file, marker, acceptance_script, missing_marker = sys.argv[1:7]
source_content = Path(source_file).read_text(encoding="utf-8")
patched_content = source_content.rstrip("\n") + f"\n\n{marker}\n"
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
        "acceptance": {
            "script_path": acceptance_script,
            "timeout_seconds": 20,
            "env": {
                "STAGE7_EXPECT_CONTAINS": missing_marker,
            },
        },
    },
    "rationale": "stage7 sandbox_file acceptance fail smoke"
}, ensure_ascii=False))
PY
)"
fail_change_request_id="$(printf '%s' "$fail_change_resp" | extract_json_field "id" | tr -d '"')"
if [[ "$fail_change_request_id" =~ ^[0-9]+$ ]]; then
  pass "成功创建会触发 auto rollback 的 sandbox_file 变更单 #${fail_change_request_id}"
else
  fail "创建 failing acceptance 变更单失败: ${fail_change_resp}"
fi

fail_approve_resp="$(api_request POST "/change-requests/${fail_change_request_id}/approve" '{"note":"sandbox acceptance fail approve"}' "local_admin")"
fail_approve_status="$(printf '%s' "$fail_approve_resp" | extract_json_field "status" | tr -d '"')"
if [[ "$fail_approve_status" == "approved" ]]; then
  pass "failing acceptance 变更单已批准"
else
  fail "failing acceptance 变更单批准失败: ${fail_approve_resp}"
fi

fail_apply_resp="$(api_request POST "/change-requests/${fail_change_request_id}/apply" "" "local_admin")"
fail_apply_status="$(printf '%s' "$fail_apply_resp" | extract_json_field "status" | tr -d '"')"
fail_acceptance_status="$(printf '%s' "$fail_apply_resp" | extract_json_field "acceptance_status" | tr -d '"')"
fail_acceptance_exit_code="$(printf '%s' "$fail_apply_resp" | extract_json_field "acceptance_report.exit_code" | tr -d '"')"
fail_auto_rollback="$(printf '%s' "$fail_apply_resp" | extract_json_field "auto_rollback_applied" | tr -d '"')"
fail_auto_rollback_change_id="$(printf '%s' "$fail_apply_resp" | extract_json_field "auto_rollback_change_request_id" | tr -d '"')"
fail_auto_rollback_triggered="$(printf '%s' "$fail_apply_resp" | extract_json_field "acceptance_report.auto_rollback_triggered" | tr -d '"')"
if [[ "$fail_apply_status" == "applied" && "$fail_acceptance_status" == "failed" && "$fail_acceptance_exit_code" =~ ^[1-9][0-9]*$ && "$fail_auto_rollback" == "true" && "$fail_auto_rollback_change_id" =~ ^[0-9]+$ && "$fail_auto_rollback_triggered" == "true" ]]; then
  pass "failing acceptance 已触发 auto rollback"
else
  fail "failing acceptance 应用结果异常: ${fail_apply_resp}"
fi

if [[ ! -e "$FAIL_SANDBOX_FILE" ]]; then
  pass "failing acceptance 已在宿主 sandbox 中自动回滚"
else
  fail "failing acceptance 未自动回滚: ${FAIL_SANDBOX_FILE}"
fi

rollback_change_resp="$(api_request GET "/change-requests/${fail_auto_rollback_change_id}" "" "local_admin")"
rollback_kind="$(printf '%s' "$rollback_change_resp" | extract_json_field "proposal_kind" | tr -d '"')"
rollback_status="$(printf '%s' "$rollback_change_resp" | extract_json_field "status" | tr -d '"')"
rollback_source_id="$(printf '%s' "$rollback_change_resp" | extract_json_field "source_change_request_id" | tr -d '"')"
if [[ "$rollback_kind" == "rollback" && "$rollback_status" == "applied" && "$rollback_source_id" == "$fail_change_request_id" ]]; then
  pass "auto rollback 变更单已创建并自动应用 #${fail_auto_rollback_change_id}"
else
  fail "auto rollback 变更单状态异常: ${rollback_change_resp}"
fi

section "Verify Monitor Metrics"
overview_resp="$(api_request GET "/monitor/overview")"
acceptance_passed_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.sandbox_acceptance_passed_count" | tr -d '"')"
acceptance_failed_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.sandbox_acceptance_failed_count" | tr -d '"')"
auto_rollback_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.sandbox_auto_rollback_applied_count" | tr -d '"')"
if [[ "$acceptance_passed_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "monitor/overview 已暴露 sandbox_acceptance_passed_count=${acceptance_passed_count}"
else
  fail "monitor/overview 未返回 sandbox_acceptance_passed_count: ${overview_resp}"
fi
if [[ "$acceptance_failed_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "monitor/overview 已暴露 sandbox_acceptance_failed_count=${acceptance_failed_count}"
else
  fail "monitor/overview 未返回 sandbox_acceptance_failed_count: ${overview_resp}"
fi
if [[ "$auto_rollback_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "monitor/overview 已暴露 sandbox_auto_rollback_applied_count=${auto_rollback_count}"
else
  fail "monitor/overview 未返回 sandbox_auto_rollback_applied_count: ${overview_resp}"
fi

section "Verify Audit Logs"
acceptance_audit_resp="$(api_request GET "/audit-logs?event_type=change_request.acceptance&limit=20")"
acceptance_audit_match="$(printf '%s' "$acceptance_audit_resp" | python3 -c 'import json,sys
pass_id=int(sys.argv[1]); fail_id=int(sys.argv[2]); data=json.load(sys.stdin)
ids={int((item.get("details") or {}).get("change_request_id") or 0) for item in data}
print(pass_id in ids and fail_id in ids)' "$pass_change_request_id" "$fail_change_request_id")"
if [[ "$acceptance_audit_match" == "True" ]]; then
  pass "audit log 记录了 sandbox_file acceptance 执行"
else
  fail "audit log 未完整记录 sandbox_file acceptance: ${acceptance_audit_resp}"
fi

auto_rollback_audit_resp="$(api_request GET "/audit-logs?event_type=change_request.auto_rollback_apply&limit=20")"
auto_rollback_audit_match="$(printf '%s' "$auto_rollback_audit_resp" | python3 -c 'import json,sys
source_id=int(sys.argv[1]); rollback_id=int(sys.argv[2]); data=json.load(sys.stdin)
print(any(int((item.get("details") or {}).get("source_change_request_id") or 0)==source_id and int((item.get("details") or {}).get("rollback_change_request_id") or 0)==rollback_id for item in data))' "$fail_change_request_id" "$fail_auto_rollback_change_id")"
if [[ "$auto_rollback_audit_match" == "True" ]]; then
  pass "audit log 记录了 sandbox_file auto rollback"
else
  fail "audit log 未记录 sandbox_file auto rollback: ${auto_rollback_audit_resp}"
fi

section "Done"
log "pass_target_key: ${PASS_TARGET_KEY}"
log "fail_target_key: ${FAIL_TARGET_KEY}"
log "日志文件: $LOG_FILE"
log "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT} WARN=${WARN_COUNT}"

if (( FAIL_COUNT > 0 )); then
  exit 1
fi
