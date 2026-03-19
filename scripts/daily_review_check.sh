#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8000}"
LOG_DIR="${LOG_DIR:-/opt/ai-assistant/logs}"
mkdir -p "$LOG_DIR"

TS="$(date +%F_%H%M%S)"
LOG_FILE="${LOG_DIR}/daily_review_check_${TS}.log"

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
  local method="$1"
  local endpoint="$2"
  local body="${3:-}"
  local resp

  if [[ -n "$body" ]]; then
    resp="$(printf '%s' "$body" | docker compose -f infra/compose/docker-compose.yml exec -T api python3 - "$method" "$endpoint" <<'PY'
import http.client, sys
method = sys.argv[1]
path = sys.argv[2]
body = sys.stdin.read()
body = body if body else None
headers = {"Content-Type": "application/json"} if body else {}
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
    resp="$(docker compose -f infra/compose/docker-compose.yml exec -T api python3 - "$method" "$endpoint" <<'PY'
import http.client, sys
method = sys.argv[1]
path = sys.argv[2]
conn = http.client.HTTPConnection("localhost", 8000)
conn.request(method, path)
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
  local method="$1"
  local endpoint="$2"
  local body="${3:-}"
  local resp
  local curl_args=("curl" "-sS" "-X" "$method" "${API_BASE}${endpoint}")

  if [[ -n "$body" ]]; then
    curl_args+=("-H" "Content-Type: application/json" "-d" "$body")
  fi

  if resp="$("${curl_args[@]}" 2>/dev/null)"; then
    echo "$resp"
    return 0
  fi

  warn "API host call failed for ${method} ${endpoint}, fallback to containers 内请求"
  if ! resp="$(api_request_via_container "$method" "$endpoint" "$body")"; then
    fail "API 容器内调用失败 ${method} ${endpoint}"
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

section "Scheduler Health"
if docker compose -f infra/compose/docker-compose.yml ps scheduler | grep -q 'Up'; then
  pass "scheduler 服务运行中"
else
  fail "scheduler 服务未运行"
fi

if docker compose -f infra/compose/docker-compose.yml logs --tail=200 scheduler | grep -q 'scheduler started' || grep -q 'scheduler started' "${LOG_DIR}/scheduler.log" 2>/dev/null; then
  pass "scheduler 启动日志存在"
else
  fail "scheduler 启动日志不存在"
fi

section "Daily Review Batch Run"
review_kind="daily-check-$(date +%s)"
payload="$(REVIEW_KIND="$review_kind" python3 -c 'import json, os; print(json.dumps({"review_kind": os.environ["REVIEW_KIND"], "note": "daily review check", "session_limit": 10, "active_within_hours": 72, "force": False}, ensure_ascii=False))')"
first_resp="$(api_request POST "/reviews/daily-run" "$payload")"
created_count="$(printf '%s' "$first_resp" | python3 -c 'import json, sys; data=json.load(sys.stdin); print(len(data.get("created", [])))')"
skipped_count="$(printf '%s' "$first_resp" | python3 -c 'import json, sys; data=json.load(sys.stdin); print(len(data.get("skipped", [])))')"
if [[ "$created_count" =~ ^[0-9]+$ ]] && (( created_count >= 1 )); then
  pass "首次 daily-run 创建了 review created=${created_count}"
else
  fail "首次 daily-run 未创建 review: $first_resp"
fi

section "Daily Review Dedupe"
second_resp="$(api_request POST "/reviews/daily-run" "$payload")"
second_created="$(printf '%s' "$second_resp" | python3 -c 'import json, sys; data=json.load(sys.stdin); print(len(data.get("created", [])))')"
second_skipped="$(printf '%s' "$second_resp" | python3 -c 'import json, sys; data=json.load(sys.stdin); print(len(data.get("skipped", [])))')"
if [[ "$second_created" == "0" && "$second_skipped" =~ ^[0-9]+$ ]] && (( second_skipped >= created_count )); then
  pass "同日去重生效 skipped=${second_skipped}"
else
  fail "同日去重异常: $second_resp"
fi

section "Scheduler Run Once Smoke"
run_once_output="$(docker compose -f infra/compose/docker-compose.yml exec -T scheduler env RUN_ONCE=1 DAILY_REVIEW_KIND="${review_kind}-runonce" DAILY_REVIEW_STARTUP_DELAY_SECONDS=0 python /scripts/daily_review_scheduler.py)"
if printf '%s' "$run_once_output" | grep -q 'daily review run completed'; then
  pass "scheduler RUN_ONCE smoke 成功"
else
  fail "scheduler RUN_ONCE smoke 失败: $run_once_output"
fi

section "Done"
log "日志文件: $LOG_FILE"
log "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT} WARN=${WARN_COUNT}"

if (( FAIL_COUNT > 0 )); then
  exit 1
fi
