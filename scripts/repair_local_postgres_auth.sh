#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_FILE="${COMPOSE_FILE:-infra/compose/docker-compose.yml}"

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  source .env
fi

POSTGRES_USER="${POSTGRES_USER:-assistant}"
POSTGRES_DB="${POSTGRES_DB:-assistant}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-change_me_for_local_dev}"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgres}"

if ! docker compose -f "$COMPOSE_FILE" ps --status running "$POSTGRES_SERVICE" >/dev/null 2>&1; then
  echo "[postgres-auth] service '$POSTGRES_SERVICE' is not running"
  echo "[postgres-auth] start it first: docker compose -f $COMPOSE_FILE up -d $POSTGRES_SERVICE"
  exit 1
fi

POSTGRES_CONTAINER_ID="$(docker compose -f "$COMPOSE_FILE" ps -q "$POSTGRES_SERVICE")"
if [[ -z "$POSTGRES_CONTAINER_ID" ]]; then
  echo "[postgres-auth] failed to resolve container id for service '$POSTGRES_SERVICE'"
  exit 1
fi

POSTGRES_NETWORK="$(docker inspect "$POSTGRES_CONTAINER_ID" --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' | head -n1 | tr -d '[:space:]')"
if [[ -z "$POSTGRES_NETWORK" ]]; then
  echo "[postgres-auth] failed to resolve docker network for service '$POSTGRES_SERVICE'"
  exit 1
fi

SQL_PASSWORD="${POSTGRES_PASSWORD//\'/\'\'}"

echo "[postgres-auth] aligning role password for '$POSTGRES_USER' in database '$POSTGRES_DB'"
docker compose -f "$COMPOSE_FILE" exec -T "$POSTGRES_SERVICE" \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "ALTER USER \"$POSTGRES_USER\" WITH PASSWORD '$SQL_PASSWORD';" >/dev/null

echo "[postgres-auth] verifying TCP login through docker network '$POSTGRES_NETWORK'"
docker run --rm --network "$POSTGRES_NETWORK" -e PGPASSWORD="$POSTGRES_PASSWORD" postgres:16 \
  psql -h "$POSTGRES_SERVICE" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c 'SELECT 1;' >/dev/null

echo "[postgres-auth] password alignment completed"
echo "[postgres-auth] you can now restart api/worker if they were failing:"
echo "  docker compose -f $COMPOSE_FILE restart api worker scheduler"
