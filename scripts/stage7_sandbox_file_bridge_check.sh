#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-${ROOT_DIR}/logs}"
API_BASE="${API_BASE:-http://127.0.0.1:8000}"
SANDBOX_HOST_ROOT="${SANDBOX_HOST_ROOT:-${ROOT_DIR}/apps/api/stage7_sandbox}"
mkdir -p "$LOG_DIR"
source "${ROOT_DIR}/scripts/http_fallback.sh"

TS="$(date +%F_%H%M%S)"
LOG_FILE="${LOG_DIR}/stage7_sandbox_file_bridge_check_${TS}.log"
SOURCE_PATH="scripts/assistant_cli.py"
SOURCE_FILE="${ROOT_DIR}/${SOURCE_PATH}"
TARGET_KEY="bridge/stage7_bridge_${TS}_assistant_cli_patch.py"
SANDBOX_FILE="${SANDBOX_HOST_ROOT}/${TARGET_KEY}"
EXPECTED_CONTENT="$(python3 - <<'PY' "$SOURCE_FILE" "$TS"
from pathlib import Path
import sys

content = Path(sys.argv[1]).read_text(encoding="utf-8").rstrip("\n")
print(f"{content}\n\n# workflow proposal bridge patch experiment {sys.argv[2]}\n")
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
  pass "已读取 bridge source_path=${SOURCE_PATH}"
else
  fail "bridge source snapshot 读取失败: ${SOURCE_PATH}"
fi

section "Create Mainline Workflow Proposal Task"
task_resp="$(python3 - <<'PY' | api_request_stdin POST "/tasks" "local_admin"
import json
print(json.dumps({
    "user_input": "读取 JSON 文件 /workspace/sample.json 并整理要点"
}, ensure_ascii=False))
PY
)"
task_id="$(printf '%s' "$task_resp" | extract_json_field "id" | tr -d '"')"
if [[ "$task_id" =~ ^[0-9]+$ ]]; then
  pass "成功创建 sandbox bridge smoke task #${task_id}"
else
  fail "创建 sandbox bridge smoke task 失败: ${task_resp}"
fi

section "Wait Running Or Approval"
task_status=""
task_state=""
approval_done="false"
for _ in $(seq 1 40); do
  task_state="$(api_request GET "/tasks/${task_id}")"
  task_status="$(printf '%s' "$task_state" | extract_json_field "status" | tr -d '"')"
  if [[ "$task_status" == "waiting_approval" ]]; then
    approvals_resp="$(api_request GET "/tasks/${task_id}/approvals")"
    approval_id="$(printf '%s' "$approvals_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); pending=next((item for item in data if item.get("status")=="pending"), {}); print(pending.get("id") or "")')"
    if [[ "$approval_id" =~ ^[0-9]+$ ]]; then
      approve_resp="$(api_request POST "/approvals/${approval_id}/approve" '{"note":"sandbox bridge smoke approve"}' "local_admin")"
      if echo "$approve_resp" | grep -q '"approval approved"'; then
        pass "已批准 sandbox bridge task 审批 approval_id=${approval_id}"
        approval_done="true"
      else
        fail "sandbox bridge task 审批批准异常: ${approve_resp}"
      fi
    fi
  fi
  if [[ "$task_status" == "completed" || "$task_status" == "failed" ]]; then
    break
  fi
  sleep 1
done

if [[ "$task_status" == "completed" || "$task_status" == "failed" ]]; then
  pass "sandbox bridge task 进入终态 status=${task_status}"
else
  fail "sandbox bridge task 未进入终态: ${task_state}"
fi

summary_resp="$(api_request GET "/tasks/${task_id}/agent-runs/summary")"
summary_impl="$(printf '%s' "$summary_resp" | extract_json_field "implementation_status" | tr -d '"')"
summary_backend="$(printf '%s' "$summary_resp" | extract_json_field "execution_backend" | tr -d '"')"
summary_proposal_action="$(printf '%s' "$summary_resp" | extract_json_field "latest_workflow_proposal.action_key" | tr -d '"')"
if [[ "$summary_impl" == "task_runtime_postrun_v1" && "$summary_backend" == "mainline" && "$summary_proposal_action" == "expand_specialist_scope" ]]; then
  pass "sandbox bridge smoke task 已通过主链产出 workflow proposal"
else
  fail "sandbox bridge smoke task 未产出预期主链 proposal: ${summary_resp}"
fi

section "Resolve Workflow Proposal"
proposal_resp="$(api_request GET "/tasks/${task_id}/workflow-proposals/latest")"
proposal_id="$(printf '%s' "$proposal_resp" | extract_json_field "id" | tr -d '"')"
proposal_source="$(printf '%s' "$proposal_resp" | extract_json_field "source" | tr -d '"')"
if [[ "$proposal_id" =~ ^[0-9]+$ && "$proposal_source" == "task_runtime_postrun_v1" ]]; then
  pass "主链 workflow proposal latest 接口返回 proposal id"
else
  fail "主链 workflow proposal latest 接口异常: ${proposal_resp}"
fi

section "Preview Supported Target Types"
draft_resp="$(api_request GET "/workflow-proposals/${proposal_id}/change-request-draft")"
draft_supported_sandbox="$(printf '%s' "$draft_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); print("sandbox_file" in (data.get("supported_target_types") or []))')"
draft_target_type="$(printf '%s' "$draft_resp" | extract_json_field "target_type" | tr -d '"')"
if [[ "$draft_supported_sandbox" == "True" ]]; then
  pass "workflow proposal draft 预览已声明支持 sandbox_file target"
else
  fail "workflow proposal draft 未声明 sandbox_file target: ${draft_resp}"
fi
if [[ "$draft_target_type" == "model_route" ]]; then
  pass "自动 suggestion 仍保持 model_route，不影响显式 sandbox_file bridge"
else
  warn "自动 suggestion 已不再是 model_route: ${draft_resp}"
fi

section "Create Sandbox File Bridge Change Request"
change_resp="$(python3 - <<'PY' "$TARGET_KEY" "$SOURCE_PATH" "$SOURCE_FILE" "$TS" | api_request_stdin POST "/workflow-proposals/${proposal_id}/change-request-draft" "local_admin"
import difflib
import json
from pathlib import Path
import sys

target_key, source_path, source_file, ts = sys.argv[1:5]
source_content = Path(source_file).read_text(encoding="utf-8")
patched_content = source_content.rstrip("\n") + f"\n\n# workflow proposal bridge patch experiment {ts}\n"
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
        "patch": patch_text
    },
    "rationale": "workflow proposal sandbox_file source-patch bridge smoke"
}, ensure_ascii=False))
PY
)"
change_request_id="$(printf '%s' "$change_resp" | extract_json_field "change_request.id" | tr -d '"')"
change_status="$(printf '%s' "$change_resp" | extract_json_field "change_request.status" | tr -d '"')"
change_target_type="$(printf '%s' "$change_resp" | extract_json_field "change_request.target_type" | tr -d '"')"
change_proposal_kind="$(printf '%s' "$change_resp" | extract_json_field "change_request.proposal_kind" | tr -d '"')"
change_source_proposal_id="$(printf '%s' "$change_resp" | extract_json_field "change_request.source_workflow_proposal_id" | tr -d '"')"
change_requires_shadow="$(printf '%s' "$change_resp" | extract_json_field "change_request.requires_shadow_validation" | tr -d '"')"
change_shadow_status="$(printf '%s' "$change_resp" | extract_json_field "change_request.shadow_validation_status" | tr -d '"')"
change_patch_summary="$(printf '%s' "$change_resp" | extract_json_field "change_request.patch_summary" | tr -d '"')"
change_patch_format="$(printf '%s' "$change_resp" | extract_json_field "change_request.payload_patch.format" | tr -d '"')"
change_patch_changed_key_count="$(printf '%s' "$change_resp" | extract_json_field "change_request.payload_patch.changed_key_count" | tr -d '"')"
change_baseline_exists="$(printf '%s' "$change_resp" | extract_json_field "change_request.baseline_payload.exists" | tr -d '"')"
change_source_copy_path="$(printf '%s' "$change_resp" | extract_json_field "change_request.proposed_payload.source_copy.source_path" | tr -d '"')"
change_source_copy_kind="$(printf '%s' "$change_resp" | extract_json_field "change_request.proposed_payload.source_copy.source_kind" | tr -d '"')"
change_source_copy_hash="$(printf '%s' "$change_resp" | extract_json_field "change_request.proposed_payload.source_copy.source_hash" | tr -d '"')"
change_content_matches_source="$(printf '%s' "$change_resp" | extract_json_field "change_request.proposed_payload.source_copy.content_matches_source" | tr -d '"')"
change_source_copy_size="$(printf '%s' "$change_resp" | extract_json_field "change_request.proposed_payload.source_copy.source_size_bytes" | tr -d '"')"
change_patch_input_format="$(printf '%s' "$change_resp" | extract_json_field "change_request.proposed_payload.patch_input.format" | tr -d '"')"
change_patch_input_size="$(printf '%s' "$change_resp" | extract_json_field "change_request.proposed_payload.patch_input.input_size_bytes" | tr -d '"')"
change_patch_input_line_count="$(printf '%s' "$change_resp" | extract_json_field "change_request.proposed_payload.patch_input.line_count" | tr -d '"')"
change_patch_applied_format="$(printf '%s' "$change_resp" | extract_json_field "change_request.proposed_payload.patch_applied.format" | tr -d '"')"
change_patch_applied_base_kind="$(printf '%s' "$change_resp" | extract_json_field "change_request.proposed_payload.patch_applied.base_kind" | tr -d '"')"
change_patch_applied_hunk_count="$(printf '%s' "$change_resp" | extract_json_field "change_request.proposed_payload.patch_applied.hunk_count" | tr -d '"')"
change_patch_applied_added_line_count="$(printf '%s' "$change_resp" | extract_json_field "change_request.proposed_payload.patch_applied.added_line_count" | tr -d '"')"
change_patch_applied_removed_line_count="$(printf '%s' "$change_resp" | extract_json_field "change_request.proposed_payload.patch_applied.removed_line_count" | tr -d '"')"
change_patch_applied_content_changed="$(printf '%s' "$change_resp" | extract_json_field "change_request.proposed_payload.patch_applied.content_changed" | tr -d '"')"
if [[ "$change_request_id" =~ ^[0-9]+$ && "$change_status" == "pending" && "$change_target_type" == "sandbox_file" && "$change_proposal_kind" == "workflow_improvement" && "$change_source_proposal_id" == "$proposal_id" ]]; then
  pass "workflow proposal 成功桥接为 sandbox_file workflow_improvement change request"
else
  fail "workflow proposal 创建 sandbox_file change request 失败: ${change_resp}"
fi
if [[ "$change_requires_shadow" == "false" && "$change_shadow_status" == "not_required" ]]; then
  pass "sandbox_file workflow_improvement change request 正确跳过 shadow gate"
else
  fail "sandbox_file workflow_improvement shadow gate 状态异常: ${change_resp}"
fi
if [[ -n "$change_patch_summary" && "$change_patch_format" == "json_object_diff_v1" && "$change_patch_changed_key_count" =~ ^[1-9][0-9]*$ && "$change_baseline_exists" == "false" ]]; then
  pass "sandbox bridge change request 已暴露 patch artifact，且基线文件为空"
else
  fail "sandbox bridge change request patch artifact 异常: ${change_resp}"
fi
if [[ "$change_source_copy_path" == "$SOURCE_PATH" && "$change_source_copy_kind" == "workspace_file" && "$change_source_copy_hash" == "$SOURCE_HASH" && "$change_content_matches_source" == "false" && "$change_source_copy_size" == "$SOURCE_SIZE" ]]; then
  pass "sandbox bridge change request 已记录 source-copy 元数据，且内容已偏离源码副本"
else
  fail "sandbox bridge source-copy 元数据异常: ${change_resp}"
fi
if [[ "$change_patch_input_format" == "unified_diff" && "$change_patch_input_size" =~ ^[1-9][0-9]*$ && "$change_patch_input_line_count" =~ ^[1-9][0-9]*$ && "$change_patch_applied_format" == "unified_diff" && "$change_patch_applied_base_kind" == "source_copy" && "$change_patch_applied_hunk_count" =~ ^[1-9][0-9]*$ && "$change_patch_applied_added_line_count" =~ ^[1-9][0-9]*$ && "$change_patch_applied_removed_line_count" =~ ^[0-9]+$ && "$change_patch_applied_content_changed" == "true" ]]; then
  pass "sandbox bridge change request 已记录 source-patch 元数据"
else
  fail "sandbox bridge source-patch 元数据异常: ${change_resp}"
fi

section "Approve And Apply Bridge Change Request"
approve_resp="$(api_request POST "/change-requests/${change_request_id}/approve" '{"note":"sandbox bridge approve"}' "local_admin")"
approve_status="$(printf '%s' "$approve_resp" | extract_json_field "status" | tr -d '"')"
if [[ "$approve_status" == "approved" ]]; then
  pass "sandbox bridge change request 已批准"
else
  fail "sandbox bridge change request 批准失败: ${approve_resp}"
fi

apply_resp="$(api_request POST "/change-requests/${change_request_id}/apply" "" "local_admin")"
apply_status="$(printf '%s' "$apply_resp" | extract_json_field "status" | tr -d '"')"
rollback_ready="$(printf '%s' "$apply_resp" | extract_json_field "rollback_ready" | tr -d '"')"
if [[ "$apply_status" == "applied" ]]; then
  pass "sandbox bridge change request 已应用"
else
  fail "sandbox bridge change request 应用失败: ${apply_resp}"
fi
if [[ "$rollback_ready" == "true" ]]; then
  pass "sandbox bridge change request 已捕获 rollback artifact"
else
  fail "sandbox bridge rollback artifact 异常: ${apply_resp}"
fi

section "Verify File State"
if [[ -f "$SANDBOX_FILE" ]]; then
  actual_content="$(cat "$SANDBOX_FILE")"
  if [[ "$actual_content"$'\n' == "$EXPECTED_CONTENT" || "$actual_content" == "$EXPECTED_CONTENT" ]]; then
    pass "sandbox bridge 已把 source-patch 结果写入宿主目录且内容正确"
  else
    fail "sandbox bridge 文件内容不一致: ${SANDBOX_FILE}"
  fi
else
  fail "sandbox bridge 未写入宿主目录文件: ${SANDBOX_FILE}"
fi

overview_resp="$(api_request GET "/monitor/overview")"
sandbox_file_applied_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.sandbox_file_applied_count" | tr -d '"')"
sandbox_source_copy_applied_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.sandbox_source_copy_applied_count" | tr -d '"')"
sandbox_source_patch_applied_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage7.sandbox_source_patch_applied_count" | tr -d '"')"
if [[ "$sandbox_file_applied_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "monitor/overview 已记录 sandbox_file_applied_count=${sandbox_file_applied_count}"
else
  fail "monitor/overview 未返回 sandbox_file_applied_count: ${overview_resp}"
fi
if [[ "$sandbox_source_copy_applied_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "monitor/overview 已记录 sandbox_source_copy_applied_count=${sandbox_source_copy_applied_count}"
else
  fail "monitor/overview 未返回 sandbox_source_copy_applied_count: ${overview_resp}"
fi
if [[ "$sandbox_source_patch_applied_count" =~ ^[1-9][0-9]*$ ]]; then
  pass "monitor/overview 已记录 sandbox_source_patch_applied_count=${sandbox_source_patch_applied_count}"
else
  fail "monitor/overview 未返回 sandbox_source_patch_applied_count: ${overview_resp}"
fi

section "Rollback Bridge Change Request"
rollback_create_resp="$(api_request POST "/change-requests/${change_request_id}/rollback" "" "local_admin")"
rollback_change_id="$(printf '%s' "$rollback_create_resp" | extract_json_field "change_request.id" | tr -d '"')"
rollback_kind="$(printf '%s' "$rollback_create_resp" | extract_json_field "change_request.proposal_kind" | tr -d '"')"
if [[ "$rollback_change_id" =~ ^[0-9]+$ && "$rollback_kind" == "rollback" ]]; then
  pass "sandbox bridge 回滚变更单创建成功 #${rollback_change_id}"
else
  fail "sandbox bridge 回滚变更单创建失败: ${rollback_create_resp}"
fi

rollback_approve_resp="$(api_request POST "/change-requests/${rollback_change_id}/approve" '{"note":"sandbox bridge rollback approve"}' "local_admin")"
rollback_approve_status="$(printf '%s' "$rollback_approve_resp" | extract_json_field "status" | tr -d '"')"
if [[ "$rollback_approve_status" == "approved" ]]; then
  pass "sandbox bridge 回滚变更单已批准"
else
  fail "sandbox bridge 回滚变更单批准失败: ${rollback_approve_resp}"
fi

rollback_apply_resp="$(api_request POST "/change-requests/${rollback_change_id}/apply" "" "local_admin")"
rollback_apply_status="$(printf '%s' "$rollback_apply_resp" | extract_json_field "status" | tr -d '"')"
if [[ "$rollback_apply_status" == "applied" ]]; then
  pass "sandbox bridge 回滚变更单已应用"
else
  fail "sandbox bridge 回滚变更单应用失败: ${rollback_apply_resp}"
fi

section "Verify Audit And Restore"
if [[ ! -e "$SANDBOX_FILE" ]]; then
  pass "sandbox bridge 文件已恢复到基线状态（不存在）"
else
  fail "sandbox bridge 文件未恢复到基线状态: ${SANDBOX_FILE}"
fi

audit_resp="$(api_request GET "/audit-logs?event_type=workflow_proposal.change_request_create&limit=20")"
audit_match="$(printf '%s' "$audit_resp" | python3 -c 'import json,sys
proposal_id=int(sys.argv[1]); change_request_id=int(sys.argv[2]); data=json.load(sys.stdin)
print(any(int((item.get("details") or {}).get("proposal_id") or 0) == proposal_id and int((item.get("details") or {}).get("change_request_id") or 0) == change_request_id and ((item.get("details") or {}).get("target_type") or "") == "sandbox_file" for item in data))' "$proposal_id" "$change_request_id")"
if [[ "$audit_match" == "True" ]]; then
  pass "audit log 记录了 workflow proposal -> sandbox_file bridge create"
else
  fail "audit log 未记录 workflow proposal -> sandbox_file bridge create: ${audit_resp}"
fi

section "Done"
log "target_key: ${TARGET_KEY}"
log "source_path: ${SOURCE_PATH}"
log "日志文件: $LOG_FILE"
log "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT} WARN=${WARN_COUNT}"

if (( FAIL_COUNT > 0 )); then
  exit 1
fi
