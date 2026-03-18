#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8000}"
LOG_DIR="${LOG_DIR:-/opt/ai-assistant/logs}"
mkdir -p "$LOG_DIR"

TS="$(date +%F_%H%M%S)"
LOG_FILE="${LOG_DIR}/governance_check_${TS}.log"

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0

log() {
  echo "[$(date '+%F %T')] $*" | tee -a "$LOG_FILE" >&2
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

api_request_via_container() {
  local actor="$1"
  local method="$2"
  local endpoint="$3"
  local body="${4:-}"
  local resp

  if [[ -n "$body" ]]; then
    resp="$(printf '%s' "$body" | docker compose -f infra/compose/docker-compose.yml exec -T api python3 - "$actor" "$method" "$endpoint" <<'PY'
import http.client, sys
actor = sys.argv[1]
method = sys.argv[2]
path = sys.argv[3]
body = sys.stdin.read()
body = body if body else None
headers = {"X-Actor-Name": actor}
if body:
    headers["Content-Type"] = "application/json"
conn = http.client.HTTPConnection("localhost", 8000)
conn.request(method, path, body, headers)
resp = conn.getresponse()
data = resp.read().decode()
sys.stdout.write(data)
if resp.status >= 400:
    sys.exit(resp.status)
PY
)"
  else
    resp="$(docker compose -f infra/compose/docker-compose.yml exec -T api python3 - "$actor" "$method" "$endpoint" <<'PY'
import http.client, sys
actor = sys.argv[1]
method = sys.argv[2]
path = sys.argv[3]
headers = {"X-Actor-Name": actor}
conn = http.client.HTTPConnection("localhost", 8000)
conn.request(method, path, headers=headers)
resp = conn.getresponse()
data = resp.read().decode()
sys.stdout.write(data)
if resp.status >= 400:
    sys.exit(resp.status)
PY
)"
  fi

  echo "$resp"
  return $?
}

api_request() {
  local actor="$1"
  local method="$2"
  local endpoint="$3"
  local body="${4:-}"
  local resp
  local curl_args=("curl" "-sS" "-X" "$method" "${API_BASE}${endpoint}" "-H" "X-Actor-Name: ${actor}")

  if [[ -n "$body" ]]; then
    curl_args+=("-H" "Content-Type: application/json" "-d" "$body")
  fi

  if resp="$("${curl_args[@]}" 2>/dev/null)"; then
    echo "$resp"
    return 0
  fi

  warn "API host call failed for ${method} ${endpoint}, fallback to containers 内请求"
  if ! resp="$(api_request_via_container "$actor" "$method" "$endpoint" "$body")"; then
    fail "API 容器内调用失败 actor=${actor} ${method} ${endpoint}"
    return 1
  fi

  echo "$resp"
}

api_request_with_status_via_container() {
  local actor="$1"
  local method="$2"
  local endpoint="$3"
  local body="${4:-}"
  local resp

  if [[ -n "$body" ]]; then
    resp="$(BODY="$body" docker compose -f infra/compose/docker-compose.yml exec -T api python3 - "$actor" "$method" "$endpoint" <<'PY'
import http.client, os, sys
actor = sys.argv[1]
method = sys.argv[2]
path = sys.argv[3]
body = os.environ.get("BODY") or None
headers = {"X-Actor-Name": actor}
if body:
    headers["Content-Type"] = "application/json"
conn = http.client.HTTPConnection("localhost", 8000)
conn.request(method, path, body, headers)
resp = conn.getresponse()
data = resp.read().decode()
sys.stdout.write(f"{resp.status}\n{data}")
PY
)"
  else
    resp="$(docker compose -f infra/compose/docker-compose.yml exec -T api python3 - "$actor" "$method" "$endpoint" <<'PY'
import http.client, sys
actor = sys.argv[1]
method = sys.argv[2]
path = sys.argv[3]
headers = {"X-Actor-Name": actor}
conn = http.client.HTTPConnection("localhost", 8000)
conn.request(method, path, headers=headers)
resp = conn.getresponse()
data = resp.read().decode()
sys.stdout.write(f"{resp.status}\n{data}")
PY
)"
  fi

  echo "$resp"
}

api_request_with_status() {
  local actor="$1"
  local method="$2"
  local endpoint="$3"
  local body="${4:-}"
  local resp

  if [[ -n "$body" ]]; then
    if resp="$(curl -sS -X "$method" "${API_BASE}${endpoint}" -H "X-Actor-Name: ${actor}" -H "Content-Type: application/json" -d "$body" -w $'\n%{http_code}' 2>/dev/null)"; then
      echo "$resp"
      return 0
    fi
  else
    if resp="$(curl -sS -X "$method" "${API_BASE}${endpoint}" -H "X-Actor-Name: ${actor}" -w $'\n%{http_code}' 2>/dev/null)"; then
      echo "$resp"
      return 0
    fi
  fi

  warn "API host call failed for ${method} ${endpoint}, fallback to containers 内请求"
  api_request_with_status_via_container "$actor" "$method" "$endpoint" "$body"
}

extract_json_field() {
  local expr="$1"
  python3 -c '
import json, sys
expr = sys.argv[1]
raw = sys.stdin.read().strip()
if not raw:
    print("")
    raise SystemExit(0)
try:
    data = json.loads(raw)
except Exception:
    print("")
    raise SystemExit(0)

current = data
for part in expr.split("."):
    if isinstance(current, dict):
        current = current.get(part)
    elif isinstance(current, list) and part.isdigit():
        idx = int(part)
        current = current[idx] if 0 <= idx < len(current) else None
    else:
        current = None
        break
print("" if current is None else current)
' "$expr"
}

section "Init DB"
init_resp="$(api_request "local_admin" POST "/init-db")"
if [[ "$(printf '%s' "$init_resp" | extract_json_field "message")" == "database initialized" ]]; then
  pass "数据库初始化成功"
else
  fail "数据库初始化返回异常: $init_resp"
fi

section "Read Governance Endpoints"
tools_resp="$(api_request "local_admin" GET "/tools")"
tool_name="$(printf '%s' "$tools_resp" | extract_json_field "0.tool_name")"
if [[ -n "$tool_name" ]]; then
  pass "工具注册表可读取 first_tool=${tool_name}"
else
  fail "工具注册表读取失败: $tools_resp"
fi

routes_resp="$(api_request "local_admin" GET "/model-routes")"
route_name="$(printf '%s' "$routes_resp" | extract_json_field "0.route_name")"
if [[ -n "$route_name" ]]; then
  pass "模型路由可读取 first_route=${route_name}"
else
  fail "模型路由读取失败: $routes_resp"
fi

providers_resp="$(api_request "local_admin" GET "/model-providers")"
provider_name="$(printf '%s' "$providers_resp" | extract_json_field "0.provider_name")"
if [[ -n "$provider_name" ]]; then
  pass "模型 provider 可读取 first_provider=${provider_name}"
else
  fail "模型 provider 读取失败: $providers_resp"
fi

changes_resp="$(api_request "local_admin" GET "/change-requests")"
if [[ "$changes_resp" == \[*\] ]]; then
  pass "变更单列表可读取"
else
  fail "变更单列表读取失败: $changes_resp"
fi

quota_resp="$(api_request "local_admin" GET "/access/quota-usage")"
quota_actor="$(printf '%s' "$quota_resp" | extract_json_field "0.actor_name")"
if [[ -n "$quota_actor" ]]; then
  pass "配额使用可读取 first_actor=${quota_actor}"
else
  fail "配额使用读取失败: $quota_resp"
fi

overview_resp="$(api_request "local_admin" GET "/monitor/overview")"
stage3_ratio="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage3.readiness_ratio")"
stage4_ratio="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage4.change_gate_coverage_ratio")"
quota_alignment="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage4.actor_quota_alignment_ok")"
stage4_applied_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage4.change_request_applied_count")"
stage4_closure_ratio="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage4.change_request_closure_ratio")"
if [[ -n "$stage3_ratio" && -n "$stage4_ratio" && -n "$stage4_applied_count" && -n "$stage4_closure_ratio" ]]; then
  pass "监控概览已返回 stage readiness 指标"
else
  fail "监控概览缺少 stage readiness 指标: $overview_resp"
fi

if [[ "$quota_alignment" == "True" || "$quota_alignment" == "true" ]]; then
  pass "actor 与 quota 当前保持对齐"
else
  fail "actor 与 quota 未对齐: $overview_resp"
fi

pre_applied_count="${stage4_applied_count:-0}"

section "Verify Direct Update Gate"
risk_policy_resp="$(api_request "local_admin" GET "/risk-policies")"
tool_registry_resp="$(api_request "local_admin" GET "/tools")"
model_route_resp="$(api_request "local_admin" GET "/model-routes")"
model_provider_resp="$(api_request "local_admin" GET "/model-providers")"
access_actor_resp="$(api_request "local_admin" GET "/access/actors")"
access_quota_resp="$(api_request "local_admin" GET "/access/quotas")"

read -r risk_policy_key risk_policy_body <<<"$(printf '%s' "$risk_policy_resp" | TARGET_KEY="approval_require_for_existing_file_overwrite" python3 -c '
import json, os, sys
rows = json.load(sys.stdin)
target = os.environ["TARGET_KEY"]
row = next((item for item in rows if item.get("policy_key") == target), None)
if not row:
    raise SystemExit(1)
print(row["policy_key"], json.dumps({"policy_value": row["policy_value"]}, ensure_ascii=False))
')"

read -r tool_name tool_body <<<"$(printf '%s' "$tool_registry_resp" | python3 -c '
import json, sys
rows = json.load(sys.stdin)
row = rows[0]
print(row["tool_name"], json.dumps({
    "enabled": row["enabled"],
    "risk_level": row["risk_level"],
    "description": row.get("description", "")
}, ensure_ascii=False))
')"

read -r route_name route_body <<<"$(printf '%s' "$model_route_resp" | python3 -c '
import json, sys
rows = json.load(sys.stdin)
row = rows[0]
print(row["route_name"], json.dumps({
    "provider": row["provider"],
    "enabled": row["enabled"],
    "model_name": row["model_name"],
    "temperature": row["temperature"],
    "max_tokens": row["max_tokens"],
    "description": row.get("description", "")
}, ensure_ascii=False))
')"

read -r provider_name provider_body <<<"$(printf '%s' "$model_provider_resp" | python3 -c '
import json, sys
rows = json.load(sys.stdin)
row = rows[0]
print(row["provider_name"], json.dumps({
    "driver": row["driver"],
    "base_url": row["base_url"],
    "api_key_env": row["api_key_env"],
    "enabled": row["enabled"],
    "description": row.get("description", "")
}, ensure_ascii=False))
')"

read -r actor_name actor_role actor_description actor_body <<<"$(printf '%s' "$access_actor_resp" | TARGET_NAME="local_viewer" python3 -c '
import json, os, sys
rows = json.load(sys.stdin)
target = os.environ["TARGET_NAME"]
row = next((item for item in rows if item.get("actor_name") == target), None)
if not row:
    raise SystemExit(1)
print(
    row["actor_name"],
    row["role"],
    row.get("description", ""),
    json.dumps({"role": row["role"], "description": row.get("description", "")}, ensure_ascii=False),
)
')"

read -r quota_actor_name quota_daily_limit quota_active_limit quota_body <<<"$(printf '%s' "$access_quota_resp" | TARGET_NAME="local_viewer" python3 -c '
import json, os, sys
rows = json.load(sys.stdin)
target = os.environ["TARGET_NAME"]
row = next((item for item in rows if item.get("actor_name") == target), None)
if not row:
    raise SystemExit(1)
print(
    row["actor_name"],
    row["daily_task_limit"],
    row["active_task_limit"],
    json.dumps({
        "daily_task_limit": row["daily_task_limit"],
        "active_task_limit": row["active_task_limit"],
    }, ensure_ascii=False),
)
')"

gate_targets=(
  "risk_policy|/risk-policies/${risk_policy_key}|${risk_policy_body}|409"
  "tool_registry|/tools/${tool_name}|${tool_body}|409"
  "model_route|/model-routes/${route_name}|${route_body}|409"
  "model_provider|/model-providers/${provider_name}|${provider_body}|409"
  "access_actor|/access/actors/${actor_name}|${actor_body}|200"
  "access_quota|/access/quotas/${quota_actor_name}|${quota_body}|200"
)

for target in "${gate_targets[@]}"; do
  IFS='|' read -r target_type endpoint body expected_status <<<"$target"
  direct_update_resp="$(api_request_with_status "local_admin" PUT "$endpoint" "$body")"
  direct_update_status="$(printf '%s' "$direct_update_resp" | tail -n 1)"
  direct_update_body="$(printf '%s' "$direct_update_resp" | sed '$d')"
  if [[ "$direct_update_status" == "$expected_status" ]]; then
    if [[ "$expected_status" == "409" ]]; then
      pass "受门禁保护的直改接口已拒绝 target=${target_type} status=409"
    else
      pass "允许直改的接口保持可写 target=${target_type} status=200"
    fi
  else
    fail "直改矩阵不符合预期 target=${target_type} expected=${expected_status} status=${direct_update_status} body=${direct_update_body}"
  fi
done

section "Create Change Request As Operator"
target_actor="governance_smoke_${TS}"
create_body="$(TARGET_ACTOR="$target_actor" python3 -c 'import json, os; print(json.dumps({"target_type": "access_actor", "target_key": os.environ["TARGET_ACTOR"], "proposed_payload": {"role": "viewer", "description": "governance smoke actor"}, "rationale": "治理专项验收创建只读 actor"}, ensure_ascii=False))')"
create_resp="$(api_request "local_operator" POST "/change-requests" "$create_body")"
change_request_id="$(printf '%s' "$create_resp" | extract_json_field "id")"
change_request_status="$(printf '%s' "$create_resp" | extract_json_field "status")"
requested_by="$(printf '%s' "$create_resp" | extract_json_field "requested_by_actor")"
if [[ -n "$change_request_id" && "$change_request_status" == "pending" && "$requested_by" == "local_operator" ]]; then
  pass "operator 创建变更单成功 id=${change_request_id}"
else
  fail "operator 创建变更单失败: $create_resp"
  exit 1
fi

section "Approve And Apply As Admin"
approve_resp="$(api_request "local_admin" POST "/change-requests/${change_request_id}/approve" '{"note":"governance check approve"}')"
approved_status="$(printf '%s' "$approve_resp" | extract_json_field "status")"
reviewed_by="$(printf '%s' "$approve_resp" | extract_json_field "reviewed_by_actor")"
if [[ "$approved_status" == "approved" && "$reviewed_by" == "local_admin" ]]; then
  pass "admin 批准变更单成功 id=${change_request_id}"
else
  fail "admin 批准变更单失败: $approve_resp"
  exit 1
fi

apply_resp="$(api_request "local_admin" POST "/change-requests/${change_request_id}/apply")"
applied_status="$(printf '%s' "$apply_resp" | extract_json_field "status")"
applied_by="$(printf '%s' "$apply_resp" | extract_json_field "applied_by_actor")"
if [[ "$applied_status" == "applied" && "$applied_by" == "local_admin" ]]; then
  pass "admin 应用变更单成功 id=${change_request_id}"
else
  fail "admin 应用变更单失败: $apply_resp"
  exit 1
fi

section "Verify Applied Target"
actors_resp="$(api_request "local_admin" GET "/access/actors")"
created_actor_name="$(printf '%s' "$actors_resp" | TARGET_ACTOR="$target_actor" python3 -c 'import json, os, sys; rows=json.load(sys.stdin); target=os.environ["TARGET_ACTOR"]; row=next((r for r in rows if r.get("actor_name")==target), {}); print(row.get("actor_name",""))')"
created_actor_role="$(printf '%s' "$actors_resp" | TARGET_ACTOR="$target_actor" python3 -c 'import json, os, sys; rows=json.load(sys.stdin); target=os.environ["TARGET_ACTOR"]; row=next((r for r in rows if r.get("actor_name")==target), {}); print(row.get("role",""))')"
if [[ "$created_actor_name" == "$target_actor" && "$created_actor_role" == "viewer" ]]; then
  pass "变更目标已生效 actor=${target_actor} role=viewer"
else
  fail "变更目标未生效: $actors_resp"
fi

section "Check Applied Change Listing"
applied_list_resp="$(api_request "local_admin" GET "/change-requests?status=applied&target_type=access_actor")"
applied_id="$(printf '%s' "$applied_list_resp" | TARGET_ID="$change_request_id" python3 -c 'import json, os, sys; rows=json.load(sys.stdin); target=os.environ["TARGET_ID"]; row=next((r for r in rows if str(r.get("id",""))==target), {}); print(row.get("id",""))')"
if [[ "$applied_id" == "$change_request_id" ]]; then
  pass "已应用变更单可按筛选条件查询 id=${change_request_id}"
else
  fail "按筛选条件查询已应用变更单失败: $applied_list_resp"
fi

section "Verify Readiness After Change"
post_overview_resp="$(api_request "local_admin" GET "/monitor/overview")"
post_actor_count="$(printf '%s' "$post_overview_resp" | extract_json_field "readiness_metrics.stage4.access_actor_count")"
post_quota_count="$(printf '%s' "$post_overview_resp" | extract_json_field "readiness_metrics.stage4.access_quota_count")"
post_quota_alignment="$(printf '%s' "$post_overview_resp" | extract_json_field "readiness_metrics.stage4.actor_quota_alignment_ok")"
post_applied_count="$(printf '%s' "$post_overview_resp" | extract_json_field "readiness_metrics.stage4.change_request_applied_count")"
post_closure_ratio="$(printf '%s' "$post_overview_resp" | extract_json_field "readiness_metrics.stage4.change_request_closure_ratio")"
if [[ -n "$post_actor_count" && -n "$post_quota_count" ]]; then
  pass "变更后监控概览仍可读取治理 readiness 计数"
else
  fail "变更后监控概览缺少治理 readiness 计数: $post_overview_resp"
fi

if [[ -n "$post_applied_count" && -n "$post_closure_ratio" ]]; then
  pass "变更后监控概览返回治理结果指标 applied_count=${post_applied_count} closure_ratio=${post_closure_ratio}"
else
  fail "变更后监控概览缺少治理结果指标: $post_overview_resp"
fi

if [[ "${post_applied_count:-0}" -gt "${pre_applied_count:-0}" ]]; then
  pass "已应用变更单计数已增长 pre=${pre_applied_count} post=${post_applied_count}"
else
  fail "已应用变更单计数未增长 pre=${pre_applied_count} post=${post_applied_count}"
fi

if [[ "$post_quota_alignment" == "True" || "$post_quota_alignment" == "true" ]]; then
  pass "应用 access_actor 变更后 actor/quota 对齐仍成立"
else
  warn "应用 access_actor 变更后 actor/quota 未对齐，后续应考虑自动补 quota 或显式提示"
fi

section "Verify Audit Trail"
audit_create_resp="$(api_request "local_admin" GET "/audit-logs?event_type=change_request.create&limit=20")"
audit_approve_resp="$(api_request "local_admin" GET "/audit-logs?event_type=change_request.approve&limit=20")"
audit_apply_resp="$(api_request "local_admin" GET "/audit-logs?event_type=change_request.apply&limit=20")"
audit_create_hit="$(printf '%s' "$audit_create_resp" | TARGET_ID="$change_request_id" python3 -c 'import json, os, sys; rows=json.load(sys.stdin); target=os.environ["TARGET_ID"]; print("yes" if any(str((row.get("details") or {}).get("change_request_id","")) == target for row in rows) else "no")')"
audit_approve_hit="$(printf '%s' "$audit_approve_resp" | TARGET_ID="$change_request_id" python3 -c 'import json, os, sys; rows=json.load(sys.stdin); target=os.environ["TARGET_ID"]; print("yes" if any(str((row.get("details") or {}).get("change_request_id","")) == target for row in rows) else "no")')"
audit_apply_hit="$(printf '%s' "$audit_apply_resp" | TARGET_ID="$change_request_id" python3 -c 'import json, os, sys; rows=json.load(sys.stdin); target=os.environ["TARGET_ID"]; print("yes" if any(str((row.get("details") or {}).get("change_request_id","")) == target for row in rows) else "no")')"
if [[ "$audit_create_hit" == "yes" && "$audit_approve_hit" == "yes" && "$audit_apply_hit" == "yes" ]]; then
  pass "变更单 create/approve/apply 审计链完整"
else
  fail "变更单审计链不完整 create=${audit_create_hit} approve=${audit_approve_hit} apply=${audit_apply_hit}"
fi

section "Done"
log "日志文件: $LOG_FILE"
log "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT} WARN=${WARN_COUNT}"

if (( FAIL_COUNT > 0 )); then
  exit 1
fi
