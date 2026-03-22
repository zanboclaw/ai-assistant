#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTAINER_ROOT="${CONTAINER_ROOT:-/workspace_repo}"
API_BASE="${API_BASE:-http://localhost:8000}"
ACTOR_NAME="${ACTOR_NAME:-local_admin}"
TOOL_NAME="${TOOL_NAME:-mcp_stdio_echo}"

echo "== Register MCP tool =="
curl -sS -X POST "${API_BASE}/change-requests" \
  -H "Content-Type: application/json" \
  -H "X-Actor-Name: ${ACTOR_NAME}" \
  -d "{
    \"target_type\": \"tool_registry\",
    \"target_key\": \"${TOOL_NAME}\",
    \"proposed_payload\": {
      \"enabled\": true,
      \"provider_type\": \"mcp_stdio\",
      \"transport\": \"stdio\",
      \"server_name\": \"local_echo_server\",
      \"provider_config\": {
        \"command\": [\"python3\", \"${CONTAINER_ROOT}/scripts/mcp_stdio_echo.py\"],
        \"timeout\": 10
      },
      \"risk_level\": \"low\",
      \"approval_required\": false,
      \"description\": \"stage8 p0 mcp stdio echo smoke\"
    },
    \"rationale\": \"register minimal mcp stdio echo tool for p0 smoke\"
  }" >/tmp/mcp_tool_registry_set.json
cat /tmp/mcp_tool_registry_set.json

CHANGE_REQUEST_ID="$(python3 - <<'PY'
import json
from pathlib import Path
data = json.loads(Path('/tmp/mcp_tool_registry_set.json').read_text())
print(int(data['id']))
PY
)"

curl -sS -X POST "${API_BASE}/change-requests/${CHANGE_REQUEST_ID}/approve" \
  -H "Content-Type: application/json" \
  -H "X-Actor-Name: ${ACTOR_NAME}" \
  -d '{"note":"approve mcp tool smoke"}' >/tmp/mcp_tool_registry_approve.json
cat /tmp/mcp_tool_registry_approve.json

curl -sS -X POST "${API_BASE}/change-requests/${CHANGE_REQUEST_ID}/apply" \
  -H "Content-Type: application/json" \
  -H "X-Actor-Name: ${ACTOR_NAME}" \
  -d '{}' >/tmp/mcp_tool_registry_apply.json
cat /tmp/mcp_tool_registry_apply.json

echo
echo "== Verify tool registry API =="
curl -sS -H "X-Actor-Name: ${ACTOR_NAME}" "${API_BASE}/tools" > /tmp/mcp_tool_registry_list.json
python3 - <<'PY'
import json
from pathlib import Path

items = json.loads(Path("/tmp/mcp_tool_registry_list.json").read_text())
match = next((item for item in items if item["tool_name"] == "mcp_stdio_echo"), None)
assert match, "mcp_stdio_echo not found in /tools"
assert match["provider_type"] == "mcp_stdio", match
assert match["transport"] == "stdio", match
assert match["server_name"] == "local_echo_server", match
print(json.dumps(match, ensure_ascii=False, indent=2))
PY

echo
echo "== Execute MCP tool via worker adapter =="
docker compose -f "${ROOT_DIR}/infra/compose/docker-compose.yml" exec -T worker python - <<'PY'
from apps.worker.worker import execute_tool, load_tool_registry_settings

settings = load_tool_registry_settings(force_refresh=True)
assert settings["mcp_stdio_echo"]["provider_type"] == "mcp_stdio", settings["mcp_stdio_echo"]
result = execute_tool("mcp_stdio_echo", {"message": "hello mcp"})
assert result["ok"] is True, result
assert "hello mcp" in result["output_text"], result
assert result["output_data"]["echo"] == "hello mcp", result
print(result["output_text"])
PY

echo
echo "PASS: MCP tool registry smoke completed"
