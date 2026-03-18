#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8000}"
REVIEW_KIND="${REVIEW_KIND:-daily}"
SESSION_LIMIT="${SESSION_LIMIT:-20}"
ACTIVE_WITHIN_HOURS="${ACTIVE_WITHIN_HOURS:-24}"
NOTE="${NOTE:-}"
FORCE="${FORCE:-0}"

payload="$(python3 - <<'PY'
import json, os
print(json.dumps({
    "review_kind": os.environ.get("REVIEW_KIND", "daily"),
    "note": os.environ.get("NOTE", ""),
    "session_limit": int(os.environ.get("SESSION_LIMIT", "20")),
    "active_within_hours": int(os.environ.get("ACTIVE_WITHIN_HOURS", "24")),
    "force": os.environ.get("FORCE", "0") in {"1", "true", "TRUE", "yes", "YES"},
}, ensure_ascii=False))
PY
)"

curl -sS -X POST "${API_BASE}/reviews/daily-run" \
  -H "Content-Type: application/json" \
  -d "$payload"
