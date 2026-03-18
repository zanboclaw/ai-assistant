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

section "Done"
log "日志文件: $LOG_FILE"
log "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT} WARN=${WARN_COUNT}"

if (( FAIL_COUNT > 0 )); then
  exit 1
fi
