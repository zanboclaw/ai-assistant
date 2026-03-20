#!/usr/bin/env bash

if [[ -n "${AI_ASSISTANT_HTTP_FALLBACK_LOADED:-}" ]]; then
  return 0
fi
AI_ASSISTANT_HTTP_FALLBACK_LOADED=1

HTTP_FALLBACK_ROOT_DIR="${ROOT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
COMPOSE_FILE="${COMPOSE_FILE:-${HTTP_FALLBACK_ROOT_DIR}/infra/compose/docker-compose.yml}"
API_BASE="${API_BASE:-http://localhost:8000}"
WEB_BASE="${WEB_BASE:-http://localhost:8080}"
HTTP_FALLBACK_CURL_MAX_TIME="${HTTP_FALLBACK_CURL_MAX_TIME:-5}"
HTTP_FALLBACK_CONTAINER_TIMEOUT_SECONDS="${HTTP_FALLBACK_CONTAINER_TIMEOUT_SECONDS:-180}"

http_fallback_warn() {
  if declare -F warn >/dev/null 2>&1; then
    warn "$*" >&2
  else
    echo "WARN: $*" >&2
  fi
}

http_fallback_warn_once() {
  local key="$1"
  local message="$2"
  local flag_var="HTTP_FALLBACK_WARNED_${key}"
  if [[ "${!flag_var:-0}" != "1" ]]; then
    printf -v "$flag_var" '%s' "1"
    http_fallback_warn "$message"
  fi
}

check_api_ready() {
  if curl -sS --max-time "$HTTP_FALLBACK_CURL_MAX_TIME" "${API_BASE}/" >/dev/null 2>&1; then
    return 0
  fi

  docker compose -f "$COMPOSE_FILE" exec -T api python3 - <<'PY' >/dev/null
import http.client

conn = http.client.HTTPConnection("localhost", 8000, timeout=5)
conn.request("GET", "/")
resp = conn.getresponse()
resp.read()
raise SystemExit(0 if resp.status < 500 else 1)
PY
}

check_web_ready() {
  if curl -sS --max-time "$HTTP_FALLBACK_CURL_MAX_TIME" "${WEB_BASE}/" >/dev/null 2>&1; then
    return 0
  fi

  docker compose -f "$COMPOSE_FILE" exec -T web wget -qO- "http://localhost/" >/dev/null
}

api_request_via_container_with_status() {
  local method="$1"
  local endpoint="$2"
  local body="${3:-}"
  local actor="${4:-}"

  if [[ -n "$body" ]]; then
    docker compose -f "$COMPOSE_FILE" exec -T api python3 - "$method" "$endpoint" "$actor" "$body" "$HTTP_FALLBACK_CONTAINER_TIMEOUT_SECONDS" <<'PY'
import http.client
import sys

method = sys.argv[1]
path = sys.argv[2]
actor = (sys.argv[3] or "").strip()
body = sys.argv[4] if len(sys.argv) > 4 else ""
body = body if body else None
headers = {}
if body is not None:
    headers["Content-Type"] = "application/json"
if actor:
    headers["X-Actor-Name"] = actor
timeout_seconds = float(sys.argv[5]) if len(sys.argv) > 5 else 180.0
conn = http.client.HTTPConnection("localhost", 8000, timeout=timeout_seconds)
conn.request(method, path, body, headers)
resp = conn.getresponse()
data = resp.read().decode()
print(resp.status)
sys.stdout.write(data)
PY
  else
    docker compose -f "$COMPOSE_FILE" exec -T api python3 - "$method" "$endpoint" "$actor" "$HTTP_FALLBACK_CONTAINER_TIMEOUT_SECONDS" <<'PY'
import http.client
import sys

method = sys.argv[1]
path = sys.argv[2]
actor = (sys.argv[3] or "").strip()
timeout_seconds = float(sys.argv[4]) if len(sys.argv) > 4 else 180.0
headers = {}
if actor:
    headers["X-Actor-Name"] = actor
conn = http.client.HTTPConnection("localhost", 8000, timeout=timeout_seconds)
conn.request(method, path, headers=headers)
resp = conn.getresponse()
data = resp.read().decode()
print(resp.status)
sys.stdout.write(data)
PY
  fi
}

api_request_via_container() {
  local resp
  resp="$(api_request_via_container_with_status "$@")" || return 1
  printf '%s' "$resp" | sed '1d'
}

api_request_with_status() {
  local method="$1"
  local endpoint="$2"
  local body="${3:-}"
  local actor="${4:-}"
  local response_file
  local status
  local resp
  local curl_exit=0
  local curl_args

  response_file="$(mktemp)"

  curl_args=("curl" "-sS" "--max-time" "$HTTP_FALLBACK_CURL_MAX_TIME" "-o" "$response_file" "-w" "%{http_code}" "-X" "$method" "${API_BASE}${endpoint}")
  if [[ -n "$actor" ]]; then
    curl_args+=("-H" "X-Actor-Name: ${actor}")
  fi

  if [[ -n "$body" ]]; then
    curl_args+=("-H" "Content-Type: application/json" "-d" "@-")
    status="$(printf '%s' "$body" | "${curl_args[@]}" 2>/dev/null)" || curl_exit=$?
  else
    status="$("${curl_args[@]}" 2>/dev/null)" || curl_exit=$?
  fi

  if (( curl_exit == 0 )); then
    printf '%s\n' "$status"
    cat "$response_file"
    rm -f "$response_file"
    return 0
  fi

  rm -f "$response_file"
  http_fallback_warn_once "API" "API host call failed for ${method} ${endpoint}, fallback to containers 内请求"
  resp="$(api_request_via_container_with_status "$method" "$endpoint" "$body" "$actor")" || return 1
  printf '%s' "$resp"
}

api_request() {
  local method="$1"
  local endpoint="$2"
  local body="${3:-}"
  local actor="${4:-}"
  local resp
  local curl_exit=0
  local curl_args

  curl_args=("curl" "-sS" "--max-time" "$HTTP_FALLBACK_CURL_MAX_TIME" "-X" "$method" "${API_BASE}${endpoint}")
  if [[ -n "$actor" ]]; then
    curl_args+=("-H" "X-Actor-Name: ${actor}")
  fi
  if [[ -n "$body" ]]; then
    curl_args+=("-H" "Content-Type: application/json" "-d" "@-")
    resp="$(printf '%s' "$body" | "${curl_args[@]}" 2>/dev/null)" || curl_exit=$?
  else
    resp="$("${curl_args[@]}" 2>/dev/null)" || curl_exit=$?
  fi

  if (( curl_exit == 0 )); then
    printf '%s' "$resp"
    return 0
  fi

  http_fallback_warn_once "API" "API host call failed for ${method} ${endpoint}, fallback to containers 内请求"
  api_request_via_container "$method" "$endpoint" "$body" "$actor"
}

api_request_stdin() {
  local method="$1"
  local endpoint="$2"
  local actor="${3:-}"
  local body
  body="$(cat)"
  api_request "$method" "$endpoint" "$body" "$actor"
}

api_request_stdin_with_status() {
  local method="$1"
  local endpoint="$2"
  local actor="${3:-}"
  local body
  body="$(cat)"
  api_request_with_status "$method" "$endpoint" "$body" "$actor"
}

fetch_web_html() {
  if curl -sS --max-time "$HTTP_FALLBACK_CURL_MAX_TIME" "${WEB_BASE}/" 2>/dev/null; then
    return 0
  fi

  http_fallback_warn_once "WEB" "宿主 Web 端口不可达，回退到 web 容器内读取"
  docker compose -f "$COMPOSE_FILE" exec -T web wget -qO- "http://localhost/"
}
