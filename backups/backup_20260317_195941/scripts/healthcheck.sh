#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="${ROOT}/infra/compose/docker-compose.yml"

check_url() {
  local url="$1"
  if ! curl -sS -o /dev/null "$url"; then
    echo "unhealthy: $url" >&2
    return 1
  fi
  echo "ok: $url"
}

check_service() {
  local service="$1"
  if ! docker compose -f "${COMPOSE_FILE}" ps "${service}" | grep -q 'Up'; then
    echo "service ${service} not up" >&2
    return 1
  fi
  echo "service up: ${service}"
}

check_url "http://localhost:8000/"
check_url "http://localhost:8080/"
check_service "api"
check_service "worker"
