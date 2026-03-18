#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/infra/compose/docker-compose.yml"
LOG_DIR="${LOG_DIR:-${ROOT_DIR}/logs}"
mkdir -p "$LOG_DIR"

TS="$(date +%F_%H%M%S)"
LOG_FILE="${LOG_DIR}/web_console_check_${TS}.log"

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

fetch_web_html() {
  if curl -sS "http://localhost:8080/" 2>/dev/null; then
    return 0
  fi

  warn "宿主 8080 不可达，回退到 web 容器内读取"
  docker compose -f "$COMPOSE_FILE" exec -T web wget -qO- "http://localhost/"
}

assert_contains() {
  local html="$1"
  local needle="$2"
  local description="$3"
  if grep -Fq "$needle" <<<"$html"; then
    pass "$description"
  else
    fail "$description"
  fi
}

section "Fetch Web Console"
html="$(fetch_web_html)"
if [[ -n "$html" ]]; then
  pass "成功读取 Web 控制台 HTML"
else
  fail "未能读取 Web 控制台 HTML"
  exit 1
fi

section "Check Key Tabs"
assert_contains "$html" "AI Assistant 工作台" "页面标题存在"
assert_contains "$html" "任务列表" "任务列表主页签存在"
assert_contains "$html" "任务详情" "任务详情主页签存在"
assert_contains "$html" "Sessions" "Sessions 主页签存在"
assert_contains "$html" "治理区" "治理区主页签存在"
assert_contains "$html" "监控区" "监控区主页签存在"

section "Check Stage 3 Session Console"
assert_contains "$html" "Sessions 工作台" "独立 Sessions 工作台存在"
assert_contains "$html" "Session Health" "Session Health 面板存在"
assert_contains "$html" "编辑 State" "Session State 编辑入口存在"
assert_contains "$html" "Task Agent Runs" "任务级 Agent 面板存在"

section "Check Stage 4 Governance And Monitor"
assert_contains "$html" "Stage Readiness" "监控页 Stage Readiness 区块存在"
assert_contains "$html" "已应用变更单" "治理结果指标存在"
assert_contains "$html" "变更闭环率" "治理闭环率指标存在"
assert_contains "$html" "Actor Context" "治理 actor 上下文存在"
assert_contains "$html" "Stage 5 基础观测" "Stage 5 基础观测区块存在"
assert_contains "$html" "最近 Agent Runs" "最近 Agent Runs 区块存在"

section "Done"
log "日志文件: $LOG_FILE"
log "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT} WARN=${WARN_COUNT}"

if (( FAIL_COUNT > 0 )); then
  exit 1
fi
