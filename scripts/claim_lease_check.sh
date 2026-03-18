#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8000}"
WORKSPACE_BASE="${WORKSPACE_BASE:-/opt/ai-assistant/data/workspace}"
LOG_DIR="${LOG_DIR:-/opt/ai-assistant/logs}"
CLAIM_KEY_PREFIX="task_claim"

mkdir -p "$LOG_DIR"
mkdir -p "$WORKSPACE_BASE"

TS="$(date +%F_%H%M%S)"
LOG_FILE="${LOG_DIR}/claim_lease_check_${TS}.log"

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

require_cmd() {
  local cmd="$1"
  if command -v "$cmd" >/dev/null 2>&1; then
    pass "命令存在: $cmd"
  else
    fail "缺少命令: $cmd"
    exit 1
  fi
}

post_json() {
  local method="$1"
  local endpoint="$2"
  local body="${3:-}"
  api_request "$method" "$endpoint" "$body"
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

wait_for_task_status() {
  local task_id="$1"
  local expected_status="$2"
  local max_wait="${3:-90}"
  local interval="${4:-2}"

  local start_ts now elapsed resp status
  start_ts="$(date +%s)"

  while true; do
    if ! resp="$(api_request GET "/tasks/${task_id}")"; then
      fail "无法读取 task ${task_id}"
      echo "error"
      return 0
    fi
    status="$(printf '%s' "$resp" | extract_json_field "status")"

    if [[ "$status" == "$expected_status" ]]; then
      echo "$status"
      return 0
    fi

    now="$(date +%s)"
    elapsed=$((now - start_ts))
    if (( elapsed >= max_wait )); then
      echo "${status:-timeout}"
      return 0
    fi

    sleep "$interval"
  done
}

wait_for_task_final() {
  local task_id="$1"
  local max_wait="${2:-180}"
  local interval="${3:-2}"

  local start_ts now elapsed resp status
  start_ts="$(date +%s)"

  while true; do
    if ! resp="$(api_request GET "/tasks/${task_id}")"; then
      fail "无法读取 task ${task_id}"
      echo "error"
      return 0
    fi
    status="$(printf '%s' "$resp" | extract_json_field "status")"

    if [[ "$status" == "completed" || "$status" == "failed" ]]; then
      echo "$status"
      return 0
    fi

    now="$(date +%s)"
    elapsed=$((now - start_ts))
    if (( elapsed >= max_wait )); then
      echo "${status:-timeout}"
      return 0
    fi

    sleep "$interval"
  done
}

wait_for_task_terminal_or_pause() {
  local task_id="$1"
  local max_wait="${2:-60}"
  local interval="${3:-2}"

  local start_ts now elapsed resp status
  start_ts="$(date +%s)"

  while true; do
    if ! resp="$(api_request GET "/tasks/${task_id}")"; then
      echo "error"
      return 0
    fi
    status="$(printf '%s' "$resp" | extract_json_field "status")"

    if [[ "$status" == "completed" || "$status" == "failed" || "$status" == "waiting_approval" || "$status" == "paused" ]]; then
      echo "$status"
      return 0
    fi

    now="$(date +%s)"
    elapsed=$((now - start_ts))
    if (( elapsed >= max_wait )); then
      echo "${status:-timeout}"
      return 0
    fi

    sleep "$interval"
  done
}

wait_for_worker_log() {
  local pattern="$1"
  local max_wait="${2:-120}"
  local interval="${3:-2}"

  local start_ts now elapsed
  start_ts="$(date +%s)"

  while true; do
    if [[ -f "${LOG_DIR}/worker.log" ]] && grep -F "$pattern" "${LOG_DIR}/worker.log" >/dev/null 2>&1; then
      return 0
    fi

    now="$(date +%s)"
    elapsed=$((now - start_ts))
    if (( elapsed >= max_wait )); then
      return 1
    fi

    sleep "$interval"
  done
}

json_body() {
  local user_input="$1"
  python3 -c 'import json, sys; print(json.dumps({"user_input": sys.argv[1]}, ensure_ascii=False))' "$user_input"
}

create_task() {
  local user_input="$1"
  local payload
  payload="$(json_body "$user_input")"
  local resp
  resp="$(post_json POST "/tasks" "$payload")"
  echo "$resp"
}

determine_redis_cmd() {
  if command -v redis-cli >/dev/null 2>&1; then
    REDIS_CMD=(redis-cli -h localhost -p 6379)
  else
    REDIS_CMD=(docker compose -f infra/compose/docker-compose.yml exec -T redis redis-cli)
  fi
}

run_redis_cli() {
  "${REDIS_CMD[@]}" "$@"
}

capture_redis() {
  local tmp
  tmp="$(mktemp)"
  run_redis_cli "$@" > "$tmp" 2>/dev/null || true
  local result
  result="$(head -n 1 "$tmp" 2>/dev/null || true)"
  rm -f "$tmp"
  printf '%s' "$result"
}

api_request_via_container() {
  local method="$1"
  local endpoint="$2"
  local body="$3"
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

  warn "API host call failed for ${method} ${endpoint}, fallback to containers内请求"
  if ! resp="$(api_request_via_container "$method" "$endpoint" "$body")"; then
    fail "API 容器内调用失败 ${method} ${endpoint}"
    return 1
  fi

  echo "$resp"
}

determine_psql_cmd() {
  if command -v psql >/dev/null 2>&1; then
    PSQL_CMD=(psql -qtA postgresql://assistant:assistant123@localhost:5432/assistant)
  else
    PSQL_CMD=(docker compose -f infra/compose/docker-compose.yml exec -T postgres env PGPASSWORD=assistant123 psql -qtA -U assistant -d assistant)
  fi
}

run_psql() {
  local sql="$1"
  "${PSQL_CMD[@]}" -c "$sql"
}

check_health() {
  section "服务健康"

  if api_request GET "/" >/dev/null 2>&1; then
    pass "API 可达"
  else
    fail "API 不可达 ${API_BASE}"
    return 1
  fi

  if run_redis_cli PING >/dev/null 2>&1; then
    pass "Redis 可达"
  else
    fail "无法连接 Redis"
    return 1
  fi
}

check_claim_flow() {
  section "Redis claim + 续租"
  local user_input="读取 /workspace/test_note.txt 并输出摘要"
  local resp task_id status claim_key ttl final_status

  resp="$(create_task "$user_input")"
  log "$resp"
  task_id="$(printf '%s' "$resp" | extract_json_field "id")"
  if [[ -z "$task_id" ]]; then
    fail "创建 claim 验证任务失败"
    return 1
  fi
  pass "创建任务 task_id=${task_id}"

  status="$(wait_for_task_status "$task_id" "running" 120 2)"
  if [[ "$status" == "running" ]]; then
    pass "任务进入 running"
  else
    fail "任务未进入 running，当前状态=${status}"
    return 1
  fi

  claim_key="${CLAIM_KEY_PREFIX}:${task_id}"
  ttl="$(capture_redis TTL "$claim_key")"
  if [[ -z "$ttl" ]]; then
    ttl="-2"
  fi
  if [[ "$ttl" =~ ^-?[0-9]+$ && "$ttl" -gt 0 ]]; then
    pass "锁 TTL 正常 ttl=${ttl}"
  else
    fail "未观察到有效 claim ttl=${ttl} key=${claim_key}"
    return 1
  fi

  final_status="$(wait_for_task_final "$task_id" 180 2)"
  if [[ "$final_status" == "completed" ]]; then
    pass "任务完成，claim 已释放"
  else
    fail "任务没有完成，状态=${final_status}"
    return 1
  fi

  ttl="$(capture_redis TTL "$claim_key")"
  if [[ -z "$ttl" ]]; then
    ttl="-2"
  fi
  if [[ "$ttl" == "-2" ]]; then
    pass "完成后 claim 已清理"
  else
    warn "完成后 claim 仍存在 ttl=${ttl}"
  fi
}

check_stale_requeue() {
  section "Stale 任务回收"
  local user_input="分析 /workspace/test_note.txt 并写入 /workspace/stale_check.txt"
  local resp task_id status task_json log_pattern

  resp="$(create_task "$user_input")"
  log "$resp"
  task_id="$(printf '%s' "$resp" | extract_json_field "id")"
  if [[ -z "$task_id" ]]; then
    fail "创建 stale requeue 任务失败"
    return 1
  fi
  pass "创建任务 task_id=${task_id}"

  run_psql "UPDATE task_runs SET status='running', error_message='stale requeue check', updated_at = now() - interval '400 seconds' WHERE id = ${task_id};"
  pass "标记 task_id=${task_id} 为 stale"

  run_redis_cli DEL "${CLAIM_KEY_PREFIX}:${task_id}" >/dev/null 2>&1 || true

  log_pattern="stale task requeued task_id=${task_id}"
  if wait_for_worker_log "$log_pattern" 120 2; then
    pass "worker 记录 stale requeue 日志"
  else
    fail "未观察到 stale requeue 日志 task_id=${task_id}"
    return 1
  fi

  task_json="$(api_request GET "/tasks/${task_id}")"
  status="$(printf '%s' "$task_json" | extract_json_field "status")"
  if [[ "$status" != "running" && "$status" != "interrupt_requested" && -n "$status" ]]; then
    pass "任务已脱离陈旧运行状态，当前状态=${status}"
  else
    warn "任务状态仍未明显变化: ${status:-<空>}"
  fi

  status="$(wait_for_task_terminal_or_pause "$task_id" 60 2)"
  if [[ "$status" == "completed" || "$status" == "failed" || "$status" == "waiting_approval" || "$status" == "paused" ]]; then
    pass "stale 回收后的任务进入可解释状态，当前状态=${status}"
  else
    warn "stale 回收后的任务未在预期时间内收口，当前状态=${status}"
  fi
}

main() {
  section "基础检查"
  require_cmd docker
  require_cmd curl
  require_cmd python3

  determine_redis_cmd
  determine_psql_cmd
  check_health
  check_claim_flow
  check_stale_requeue

  section "验收汇总"
  log "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT} WARN=${WARN_COUNT}"
  if (( FAIL_COUNT > 0 )); then
    exit 1
  fi
}

main "$@"
