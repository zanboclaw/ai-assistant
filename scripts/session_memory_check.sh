#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8000}"
LOG_DIR="${LOG_DIR:-/opt/ai-assistant/logs}"
mkdir -p "$LOG_DIR"

TS="$(date +%F_%H%M%S)"
LOG_FILE="${LOG_DIR}/session_memory_check_${TS}.log"

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

wait_for_task_final() {
  local task_id="$1"
  local max_wait="${2:-180}"
  local interval="${3:-2}"
  local start_ts now elapsed resp status

  start_ts="$(date +%s)"
  while true; do
    resp="$(api_request GET "/tasks/${task_id}" || true)"
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

section "Init DB"
init_resp="$(api_request POST "/init-db")"
if [[ "$(printf '%s' "$init_resp" | extract_json_field "message")" == "database initialized" ]]; then
  pass "数据库初始化成功"
else
  fail "数据库初始化返回异常: $init_resp"
fi

section "Create Session"
session_name="stage3-auto-$(date +%s)"
session_resp="$(api_request POST "/sessions" "{\"name\":\"${session_name}\",\"description\":\"stage3 auto memory check\"}")"
session_id="$(printf '%s' "$session_resp" | extract_json_field "id")"
if [[ -n "$session_id" ]]; then
  pass "创建 session 成功 session_id=${session_id}"
else
  fail "创建 session 失败: $session_resp"
  exit 1
fi

section "Create Manual Preference Memory"
pref_resp="$(api_request POST "/sessions/${session_id}/memories" '{"category":"preference","content":"偏好简洁回答","importance":4}')"
pref_id="$(printf '%s' "$pref_resp" | extract_json_field "id")"
if [[ -n "$pref_id" ]]; then
  pass "手动 memory 创建成功 memory_id=${pref_id}"
else
  fail "手动 memory 创建失败: $pref_resp"
fi

state_resp="$(api_request GET "/sessions/${session_id}/state")"
preferences_0="$(printf '%s' "$state_resp" | extract_json_field "preferences.0")"
if [[ "$preferences_0" == "偏好简洁回答" ]]; then
  pass "preference 已自动同步到 session_state"
else
  fail "preference 未同步到 session_state: $state_resp"
fi

section "Create Session Task"
workspace_target="/workspace/session_memory_check_${session_id}.md"
task_body="$(python3 -c 'import json, sys; print(json.dumps({"user_input": sys.argv[1], "session_id": int(sys.argv[2])}, ensure_ascii=False))' "读取文件 /workspace/test_note.txt 并整理要点后写入 ${workspace_target}" "$session_id")"
task_resp="$(api_request POST "/tasks" "$task_body")"
task_id="$(printf '%s' "$task_resp" | extract_json_field "id")"
if [[ -n "$task_id" ]]; then
  pass "创建 session task 成功 task_id=${task_id}"
else
  fail "创建 session task 失败: $task_resp"
  exit 1
fi

task_status="$(wait_for_task_final "$task_id" 180 2)"
if [[ "$task_status" == "completed" ]]; then
  pass "session task 已完成 task_id=${task_id}"
else
  fail "session task 未完成，最终状态=${task_status}"
fi

section "Check Auto Task Summary Memory"
memory_resp="$(api_request GET "/sessions/${session_id}/memories?category=task_summary&limit=10")"
memory_source_task_id="$(printf '%s' "$memory_resp" | extract_json_field "0.source_task_id")"
memory_category="$(printf '%s' "$memory_resp" | extract_json_field "0.category")"
if [[ "$memory_source_task_id" == "$task_id" && "$memory_category" == "task_summary" ]]; then
  pass "task_summary memory 已自动写入 source_task_id=${task_id}"
else
  fail "未找到自动 task_summary memory: $memory_resp"
fi

summary_resp="$(api_request GET "/sessions/${session_id}/summary")"
memory_total="$(printf '%s' "$summary_resp" | extract_json_field "memory_metrics.total_memories")"
task_summary_count="$(printf '%s' "$summary_resp" | extract_json_field "memory_metrics.by_category.task_summary")"
preference_count="$(printf '%s' "$summary_resp" | extract_json_field "memory_metrics.by_category.preference")"
fact_count="$(printf '%s' "$summary_resp" | extract_json_field "memory_metrics.by_category.fact")"
task_total="$(printf '%s' "$summary_resp" | extract_json_field "task_metrics.total_tasks")"
summary_text="$(printf '%s' "$summary_resp" | extract_json_field "session_state.summary_text")"
if [[ "$memory_total" =~ ^[0-9]+$ ]] && (( memory_total >= 2 )); then
  pass "session summary 的 memory total 合理"
else
  fail "session summary 的 memory total 异常: $summary_resp"
fi

if [[ "$task_total" == "1" ]]; then
  pass "session summary 的 task total 正确"
else
  fail "session summary 的 task total 异常: $summary_resp"
fi

if [[ "$task_summary_count" == "1" ]]; then
  pass "session summary 的 task_summary 分类计数正确"
else
  fail "session summary 的 task_summary 分类计数异常: $summary_resp"
fi

if [[ "$preference_count" == "1" ]]; then
  pass "session summary 的 preference 分类计数正确"
else
  fail "session summary 的 preference 分类计数异常: $summary_resp"
fi

if [[ "$fact_count" =~ ^[0-9]+$ ]] && (( fact_count >= 1 )); then
  pass "session summary 的 fact 分类计数合理"
else
  fail "session summary 的 fact 分类计数异常: $summary_resp"
fi

if [[ "$summary_text" == *"tasks=1"* && "$summary_text" == *"preferences=1"* ]]; then
  pass "session_state 摘要已自动重建"
else
  fail "session_state 摘要未按预期更新: $summary_resp"
fi

section "Check Auto Preference Extraction"
pref_task_body="$(python3 -c 'import json, sys; print(json.dumps({"user_input": sys.argv[1], "session_id": int(sys.argv[2])}, ensure_ascii=False))' "以后请用简洁分点中文回答，读取文件 /workspace/test_note.txt 并整理要点后写入 /workspace/session_memory_pref_${session_id}.md" "$session_id")"
pref_task_resp="$(api_request POST "/tasks" "$pref_task_body")"
pref_task_id="$(printf '%s' "$pref_task_resp" | extract_json_field "id")"
if [[ -n "$pref_task_id" ]]; then
  pass "创建偏好提取 task 成功 task_id=${pref_task_id}"
else
  fail "创建偏好提取 task 失败: $pref_task_resp"
  exit 1
fi

pref_task_status="$(wait_for_task_final "$pref_task_id" 180 2)"
if [[ "$pref_task_status" == "completed" ]]; then
  pass "偏好提取 task 已完成 task_id=${pref_task_id}"
else
  fail "偏好提取 task 未完成，最终状态=${pref_task_status}"
fi

pref_memory_resp="$(api_request GET "/sessions/${session_id}/memories?category=preference&limit=20")"
pref_memory_content="$(printf '%s' "$pref_memory_resp" | extract_json_field "0.content")"
if [[ "$pref_memory_content" == *"简洁"* && "$pref_memory_content" == *"分点"* && "$pref_memory_content" == *"中文"* ]]; then
  pass "自动 preference 提炼成功"
else
  fail "自动 preference 提炼未命中: $pref_memory_resp"
fi

summary_after_pref_resp="$(api_request GET "/sessions/${session_id}/summary")"
if printf '%s' "$summary_after_pref_resp" | python3 -c 'import json, sys
data = json.load(sys.stdin)
prefs = data.get("session_state", {}).get("preferences", [])
target = [str(item) for item in prefs if "简洁" in str(item) and "分点" in str(item) and "中文" in str(item)]
print("yes" if target else "no")
' | grep -q '^yes$'; then
  pass "自动提炼的 preference 已并入 session_state"
else
  fail "自动提炼的 preference 未并入 session_state: $summary_after_pref_resp"
fi

health_after_pref_resp="$(api_request GET "/sessions/${session_id}/health")"
health_pref_count="$(printf '%s' "$health_after_pref_resp" | extract_json_field "health.preference_count")"
health_state_stale="$(printf '%s' "$health_after_pref_resp" | extract_json_field "health.state_is_stale")"
if [[ "$health_pref_count" == "2" ]]; then
  pass "session health 能反映当前 preference 数量"
else
  fail "session health 的 preference_count 异常: $health_after_pref_resp"
fi

if [[ "$health_state_stale" == "False" || "$health_state_stale" == "false" ]]; then
  pass "session health 显示 state 当前未过期"
else
  fail "session health 错误地标记 state 过期: $health_after_pref_resp"
fi

section "Check Auto Follow-up Extraction"
follow_task_body="$(python3 -c 'import json, sys; print(json.dumps({"user_input": sys.argv[1], "session_id": int(sys.argv[2])}, ensure_ascii=False))' "读取文件 /workspace/test_note.txt 并整理要点，后续请继续整理 README，下一步补充 runbook 后写入 /workspace/session_memory_follow_${session_id}.md" "$session_id")"
follow_task_resp="$(api_request POST "/tasks" "$follow_task_body")"
follow_task_id="$(printf '%s' "$follow_task_resp" | extract_json_field "id")"
if [[ -n "$follow_task_id" ]]; then
  pass "创建 follow-up 提取 task 成功 task_id=${follow_task_id}"
else
  fail "创建 follow-up 提取 task 失败: $follow_task_resp"
  exit 1
fi

follow_task_status="$(wait_for_task_final "$follow_task_id" 180 2)"
if [[ "$follow_task_status" == "completed" ]]; then
  pass "follow-up 提取 task 已完成 task_id=${follow_task_id}"
else
  fail "follow-up 提取 task 未完成，最终状态=${follow_task_status}"
fi

follow_memory_resp="$(api_request GET "/sessions/${session_id}/memories?category=follow_up&limit=20")"
if printf '%s' "$follow_memory_resp" | python3 -c 'import json, sys
rows = json.load(sys.stdin)
target = [str(row.get("content", "")) for row in rows if "后续请继续整理 README" in str(row.get("content", "")) or "下一步补充 runbook" in str(row.get("content", ""))]
print("yes" if target else "no")
' | grep -q '^yes$'; then
  pass "自动 follow_up 提炼成功"
else
  fail "自动 follow_up 提炼未命中: $follow_memory_resp"
fi

summary_after_follow_resp="$(api_request GET "/sessions/${session_id}/summary")"
if printf '%s' "$summary_after_follow_resp" | python3 -c 'import json, sys
data = json.load(sys.stdin)
loops = data.get("session_state", {}).get("open_loops", [])
target = [str(item) for item in loops if "后续请继续整理 README" in str(item) or "下一步补充 runbook" in str(item)]
print("yes" if target else "no")
' | grep -q '^yes$'; then
  pass "自动提炼的 follow_up 已并入 session_state.open_loops"
else
  fail "自动提炼的 follow_up 未并入 session_state: $summary_after_follow_resp"
fi

section "Check State Rebuild Consistency"
rebuild_resp="$(api_request POST "/sessions/${session_id}/state/rebuild")"
rebuild_summary_text="$(printf '%s' "$rebuild_resp" | extract_json_field "summary_text")"
if [[ "$rebuild_summary_text" == *"tasks=3"* && "$rebuild_summary_text" == *"preferences=2"* && "$rebuild_summary_text" == *"open_loops=1"* ]]; then
  pass "state-rebuild 后摘要与当前记忆集合一致"
else
  fail "state-rebuild 后摘要异常: $rebuild_resp"
fi

summary_after_rebuild="$(api_request GET "/sessions/${session_id}/summary")"
rebuilt_task_summary_count="$(printf '%s' "$summary_after_rebuild" | extract_json_field "memory_metrics.by_category.task_summary")"
rebuilt_preference_count="$(printf '%s' "$summary_after_rebuild" | extract_json_field "memory_metrics.by_category.preference")"
rebuilt_follow_count="$(printf '%s' "$summary_after_rebuild" | extract_json_field "memory_metrics.by_category.follow_up")"
if [[ "$rebuilt_task_summary_count" == "3" && "$rebuilt_preference_count" == "2" && "$rebuilt_follow_count" == "1" ]]; then
  pass "rebuild 后分类计数保持一致"
else
  fail "rebuild 后分类计数异常: $summary_after_rebuild"
fi

health_after_rebuild_resp="$(api_request GET "/sessions/${session_id}/health")"
health_open_loop_count="$(printf '%s' "$health_after_rebuild_resp" | extract_json_field "health.open_loop_count")"
health_review_count="$(printf '%s' "$health_after_rebuild_resp" | extract_json_field "health.total_reviews")"
health_actions_raw="$(printf '%s' "$health_after_rebuild_resp" | extract_json_field "health.recommended_actions")"
summary_health_open_loops="$(printf '%s' "$summary_after_rebuild" | extract_json_field "health.open_loop_count")"
if [[ "$health_open_loop_count" == "1" && "$summary_health_open_loops" == "1" ]]; then
  pass "summary 与 health 对 open_loop_count 的视图一致"
else
  fail "summary 与 health 的 open_loop_count 不一致: summary=$summary_after_rebuild health=$health_after_rebuild_resp"
fi

if [[ "$health_review_count" == "0" ]]; then
  pass "session health 在未创建 review 时计数正确"
else
  fail "session health 的 review 计数异常: $health_after_rebuild_resp"
fi

if [[ "$health_actions_raw" == *"create_review"* ]]; then
  pass "session health 在缺 review 时给出 create_review 建议"
else
  fail "session health 未给出 create_review 建议: $health_after_rebuild_resp"
fi

section "Create Review And Verify Health"
review_resp="$(api_request POST "/sessions/${session_id}/reviews" '{"review_kind":"manual","note":"session memory check"}')"
review_id="$(printf '%s' "$review_resp" | extract_json_field "id")"
if [[ -n "$review_id" ]]; then
  pass "手动创建 session review 成功 review_id=${review_id}"
else
  fail "手动创建 session review 失败: $review_resp"
fi

health_after_review_resp="$(api_request GET "/sessions/${session_id}/health")"
health_review_count_after="$(printf '%s' "$health_after_review_resp" | extract_json_field "health.total_reviews")"
health_latest_review_at="$(printf '%s' "$health_after_review_resp" | extract_json_field "health.latest_review_at")"
if [[ "$health_review_count_after" == "1" && -n "$health_latest_review_at" ]]; then
  pass "session health 在创建 review 后已更新"
else
  fail "session health 未反映新 review: $health_after_review_resp"
fi

section "Check CLI Session Health"
cli_health_resp="$(./scripts/assistant_cli.py sessions health "$session_id")"
if [[ "$cli_health_resp" == *"duplicate_memory_count"* && "$cli_health_resp" == *"state_is_stale"* && "$cli_health_resp" == *"total_reviews"* && "$cli_health_resp" == *"recommended_actions"* ]]; then
  pass "CLI sessions health 可直接查看 Stage 3 健康信号"
else
  fail "CLI sessions health 输出缺少关键字段: $cli_health_resp"
fi

section "Verify Stage 3 Readiness Metrics"
overview_resp="$(api_request GET "/monitor/overview")"
stage3_ratio="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage3.readiness_ratio")"
stage3_operational="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage3.operational")"
stage3_ready_session_count="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage3.ready_session_count")"
stage3_missing_state="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage3.sessions_missing_state")"
stage3_missing_review="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage3.sessions_missing_review")"
stage3_duplicate_memories="$(printf '%s' "$overview_resp" | extract_json_field "readiness_metrics.stage3.sessions_with_duplicate_memories")"
if [[ -n "$stage3_ratio" && -n "$stage3_operational" && -n "$stage3_ready_session_count" && -n "$stage3_missing_state" && -n "$stage3_missing_review" && -n "$stage3_duplicate_memories" ]]; then
  pass "monitor/overview 已返回 Stage 3 readiness 指标"
else
  fail "monitor/overview 缺少 Stage 3 readiness 指标: $overview_resp"
fi

if [[ "$stage3_ratio" == "1.0" ]]; then
  pass "Stage 3 readiness_ratio 达到 1.0"
else
  fail "Stage 3 readiness_ratio 未达 1.0: $overview_resp"
fi

if [[ "$stage3_operational" == "True" || "$stage3_operational" == "true" ]]; then
  pass "Stage 3 operational 指标为 true"
else
  fail "Stage 3 operational 指标异常: $overview_resp"
fi

if [[ "$stage3_missing_state" == "0" && "$stage3_missing_review" == "0" && "$stage3_duplicate_memories" == "0" ]]; then
  pass "Stage 3 must-have 缺口计数已清零"
else
  fail "Stage 3 must-have 缺口计数异常: $overview_resp"
fi

section "Done"
log "日志文件: $LOG_FILE"
log "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT} WARN=${WARN_COUNT}"

if (( FAIL_COUNT > 0 )); then
  exit 1
fi
