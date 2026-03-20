#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-${ROOT_DIR}/logs}"
API_BASE="${API_BASE:-http://127.0.0.1:8000}"
mkdir -p "$LOG_DIR"
source "${ROOT_DIR}/scripts/http_fallback.sh"

TS="$(date +%F_%H%M%S)"
LOG_FILE="${LOG_DIR}/change_request_rollback_check_${TS}.log"

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0

log() {
  echo "[$(date '+%F %T')] $*" | tee -a "$LOG_FILE"
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

section() {
  echo | tee -a "$LOG_FILE"
  echo "========== $* ==========" | tee -a "$LOG_FILE"
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

section "Init DB"
api_request POST "/init-db" "" "local_admin" >/dev/null
pass "数据库初始化成功"

section "Capture Baseline Model Route"
routes_resp="$(api_request GET "/model-routes" "" "local_admin")"
planner_route="$(printf '%s' "$routes_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); item=next((x for x in data if x.get("route_name")=="planner"), None); print(json.dumps(item or {}, ensure_ascii=False))')"
planner_provider="$(printf '%s' "$planner_route" | extract_json_field "provider" | tr -d '"')"
planner_model="$(printf '%s' "$planner_route" | extract_json_field "model_name" | tr -d '"')"
planner_temp="$(printf '%s' "$planner_route" | extract_json_field "temperature" | tr -d '"')"
planner_tokens="$(printf '%s' "$planner_route" | extract_json_field "max_tokens" | tr -d '"')"
planner_enabled="$(printf '%s' "$planner_route" | extract_json_field "enabled" | tr -d '"')"
planner_desc_json="$(printf '%s' "$planner_route" | extract_json_field "description")"
if [[ -n "$planner_provider" && -n "$planner_model" && "$planner_tokens" =~ ^[0-9]+$ ]]; then
  pass "读取到 planner 基线配置 provider=${planner_provider} model=${planner_model} max_tokens=${planner_tokens}"
else
  fail "读取 planner 基线配置失败: ${routes_resp}"
fi

changed_tokens=$((planner_tokens + 111))
changed_desc_json="$(python3 -c 'import json,sys; desc=json.loads(sys.argv[1]); print(json.dumps(((desc or "").strip()+" | rollback-check").strip(" |"), ensure_ascii=False))' "$planner_desc_json")"

section "Create / Approve / Apply Change Request"
create_payload="$(python3 -c 'import json,sys
provider,model,temp,tokens,enabled,desc = sys.argv[1:7]
print(json.dumps({
  "target_type": "model_route",
  "target_key": "planner",
  "proposed_payload": {
    "provider": provider,
    "model_name": model,
    "temperature": float(temp),
    "max_tokens": int(tokens),
    "enabled": str(enabled).lower() == "true",
    "description": json.loads(desc)
  },
  "rationale": "stage7 rollback groundwork smoke"
}, ensure_ascii=False))' \
  "$planner_provider" "$planner_model" "$planner_temp" "$changed_tokens" "$planner_enabled" "$changed_desc_json")"

change_resp="$(printf '%s' "$create_payload" | api_request_stdin POST "/change-requests" "local_admin")"
change_request_id="$(printf '%s' "$change_resp" | extract_json_field "id" | tr -d '"')"
change_proposal_kind="$(printf '%s' "$change_resp" | extract_json_field "proposal_kind" | tr -d '"')"
if [[ "$change_request_id" =~ ^[0-9]+$ && "$change_proposal_kind" == "manual_change" ]]; then
  pass "成功创建变更单 change_request_id=${change_request_id}"
else
  fail "创建变更单失败: ${change_resp}"
fi

approve_resp="$(api_request POST "/change-requests/${change_request_id}/approve" '{"note":"rollback smoke approve"}' "local_admin")"
approve_status="$(printf '%s' "$approve_resp" | extract_json_field "status" | tr -d '"')"
if [[ "$approve_status" == "approved" ]]; then
  pass "原始变更单已批准"
else
  fail "原始变更单批准失败: ${approve_resp}"
fi

apply_resp="$(api_request POST "/change-requests/${change_request_id}/apply" "" "local_admin")"
apply_status="$(printf '%s' "$apply_resp" | extract_json_field "status" | tr -d '"')"
rollback_ready="$(printf '%s' "$apply_resp" | extract_json_field "rollback_ready" | tr -d '"')"
apply_patch_summary="$(printf '%s' "$apply_resp" | extract_json_field "patch_summary" | tr -d '"')"
apply_patch_format="$(printf '%s' "$apply_resp" | extract_json_field "payload_patch.format" | tr -d '"')"
apply_patch_changed_key_count="$(printf '%s' "$apply_resp" | extract_json_field "payload_patch.changed_key_count" | tr -d '"')"
apply_baseline_provider="$(printf '%s' "$apply_resp" | extract_json_field "baseline_payload.provider" | tr -d '"')"
if [[ "$apply_status" == "applied" ]]; then
  pass "原始变更单已应用"
else
  fail "原始变更单应用失败: ${apply_resp}"
fi
if [[ "$rollback_ready" == "true" ]]; then
  pass "应用后已生成 rollback artifact"
else
  fail "应用后未生成 rollback artifact: ${apply_resp}"
fi
if [[ -n "$apply_patch_summary" && "$apply_patch_format" == "json_object_diff_v1" && "$apply_patch_changed_key_count" =~ ^[0-9]+$ && "$apply_patch_changed_key_count" -ge 1 && -n "$apply_baseline_provider" ]]; then
  pass "原始变更单已暴露 patch artifact（baseline/payload_patch/patch_summary）"
else
  fail "原始变更单 patch artifact 字段异常: ${apply_resp}"
fi

section "Verify Rollback Draft"
draft_resp="$(api_request GET "/change-requests/${change_request_id}/rollback-draft" "" "local_admin")"
draft_ready="$(printf '%s' "$draft_resp" | extract_json_field "rollback_ready" | tr -d '"')"
draft_kind="$(printf '%s' "$draft_resp" | extract_json_field "proposal_kind" | tr -d '"')"
draft_payload_tokens="$(printf '%s' "$draft_resp" | extract_json_field "proposed_payload.max_tokens" | tr -d '"')"
draft_patch_summary="$(printf '%s' "$draft_resp" | extract_json_field "patch_summary" | tr -d '"')"
draft_patch_format="$(printf '%s' "$draft_resp" | extract_json_field "payload_patch.format" | tr -d '"')"
draft_patch_changed_key_count="$(printf '%s' "$draft_resp" | extract_json_field "payload_patch.changed_key_count" | tr -d '"')"
draft_baseline_provider="$(printf '%s' "$draft_resp" | extract_json_field "baseline_payload.provider" | tr -d '"')"
if [[ "$draft_ready" == "true" && "$draft_kind" == "rollback" ]]; then
  pass "rollback draft 可用，proposal_kind=rollback"
else
  fail "rollback draft 不可用: ${draft_resp}"
fi
if [[ "$draft_payload_tokens" == "$planner_tokens" ]]; then
  pass "rollback draft 保留了应用前 max_tokens 基线"
else
  fail "rollback draft max_tokens 与基线不一致: ${draft_resp}"
fi
if [[ -n "$draft_patch_summary" && "$draft_patch_format" == "json_object_diff_v1" && "$draft_patch_changed_key_count" =~ ^[0-9]+$ && "$draft_patch_changed_key_count" -ge 1 && -n "$draft_baseline_provider" ]]; then
  pass "rollback draft 已暴露 patch artifact（baseline/payload_patch/patch_summary）"
else
  fail "rollback draft patch artifact 字段异常: ${draft_resp}"
fi

section "Create / Approve / Apply Rollback Change Request"
rollback_create_resp="$(api_request POST "/change-requests/${change_request_id}/rollback" "" "local_admin")"
rollback_created="$(printf '%s' "$rollback_create_resp" | extract_json_field "created" | tr -d '"')"
rollback_change_id="$(printf '%s' "$rollback_create_resp" | extract_json_field "change_request.id" | tr -d '"')"
rollback_source_id="$(printf '%s' "$rollback_create_resp" | extract_json_field "change_request.source_change_request_id" | tr -d '"')"
rollback_kind="$(printf '%s' "$rollback_create_resp" | extract_json_field "change_request.proposal_kind" | tr -d '"')"
if [[ "$rollback_change_id" =~ ^[0-9]+$ && "$rollback_kind" == "rollback" && "$rollback_source_id" == "$change_request_id" ]]; then
  pass "回滚变更单创建成功 rollback_change_request_id=${rollback_change_id}"
else
  fail "回滚变更单创建失败: ${rollback_create_resp}"
fi

if [[ "$rollback_created" == "false" ]]; then
  warn "检测到已存在回滚变更单，本次复用已有记录"
fi

rollback_approve_resp="$(api_request POST "/change-requests/${rollback_change_id}/approve" '{"note":"rollback smoke approve"}' "local_admin")"
rollback_approve_status="$(printf '%s' "$rollback_approve_resp" | extract_json_field "status" | tr -d '"')"
if [[ "$rollback_approve_status" == "approved" ]]; then
  pass "回滚变更单已批准"
else
  fail "回滚变更单批准失败: ${rollback_approve_resp}"
fi

rollback_apply_resp="$(api_request POST "/change-requests/${rollback_change_id}/apply" "" "local_admin")"
rollback_apply_status="$(printf '%s' "$rollback_apply_resp" | extract_json_field "status" | tr -d '"')"
if [[ "$rollback_apply_status" == "applied" ]]; then
  pass "回滚变更单已应用"
else
  fail "回滚变更单应用失败: ${rollback_apply_resp}"
fi

section "Verify Planner Route Restored"
restored_routes_resp="$(api_request GET "/model-routes" "" "local_admin")"
restored_route="$(printf '%s' "$restored_routes_resp" | python3 -c 'import json,sys; data=json.load(sys.stdin); item=next((x for x in data if x.get("route_name")=="planner"), None); print(json.dumps(item or {}, ensure_ascii=False))')"
restored_tokens="$(printf '%s' "$restored_route" | extract_json_field "max_tokens" | tr -d '"')"
restored_desc_json="$(printf '%s' "$restored_route" | extract_json_field "description")"
if [[ "$restored_tokens" == "$planner_tokens" ]]; then
  pass "planner.max_tokens 已恢复到基线值 ${planner_tokens}"
else
  fail "planner.max_tokens 未恢复: ${restored_route}"
fi
if [[ "$restored_desc_json" == "$planner_desc_json" ]]; then
  pass "planner.description 已恢复到基线值"
else
  fail "planner.description 未恢复: ${restored_route}"
fi

section "Verify Rollback Audit"
audit_resp="$(api_request GET "/audit-logs?event_type=change_request.rollback_create&limit=20")"
audit_match="$(printf '%s' "$audit_resp" | python3 -c 'import json,sys
source_id=int(sys.argv[1]); rollback_id=int(sys.argv[2]); data=json.load(sys.stdin)
print(any(int((item.get("details") or {}).get("source_change_request_id") or 0)==source_id and int((item.get("details") or {}).get("rollback_change_request_id") or 0)==rollback_id for item in data))' "$change_request_id" "$rollback_change_id")"
if [[ "$audit_match" == "True" ]]; then
  pass "audit log 记录了 change_request.rollback_create"
else
  fail "audit log 未记录 change_request.rollback_create: ${audit_resp}"
fi

section "Done"
log "日志文件: $LOG_FILE"
log "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT} WARN=${WARN_COUNT}"

if (( FAIL_COUNT > 0 )); then
  exit 1
fi
