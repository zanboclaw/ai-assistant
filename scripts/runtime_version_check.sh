#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

API_BASE="${API_BASE:-http://localhost:8000}"
EXPECTED_VERSION="${EXPECTED_VERSION:-$(python3 - <<'PY'
import json
from pathlib import Path
payload = json.loads(Path("version.json").read_text(encoding="utf-8"))
print(payload.get("current_version", ""))
PY
)}"
EXPECTED_COMMIT="${EXPECTED_COMMIT:-$(git rev-parse HEAD 2>/dev/null || true)}"

echo "[runtime-version] checking ${API_BASE}/runtime-metadata"
payload="$(curl -fsS "${API_BASE}/runtime-metadata")"
python3 - "$payload" "$EXPECTED_VERSION" "$EXPECTED_COMMIT" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
expected_version = sys.argv[2].strip()
expected_commit = sys.argv[3].strip()

runtime_version = str(payload.get("current_version") or "")
runtime_commit = str(payload.get("git_commit") or "")
version_block = payload.get("version") or {}
if not runtime_version:
    runtime_version = str(version_block.get("current_version") or "")
if not runtime_commit:
    runtime_commit = str(version_block.get("git_commit") or "")
runtime_branch = payload.get("git_branch")
if not runtime_branch:
    runtime_branch = version_block.get("git_branch")
runtime_dirty = payload.get("git_dirty")
if runtime_dirty in (None, ""):
    runtime_dirty = version_block.get("git_dirty")

if expected_version and runtime_version != expected_version:
    raise SystemExit(f"runtime version mismatch: expected={expected_version} actual={runtime_version}")
if expected_commit and runtime_commit and runtime_commit != expected_commit:
    raise SystemExit(f"runtime commit mismatch: expected={expected_commit} actual={runtime_commit}")

print(json.dumps({
    "current_version": runtime_version,
    "git_commit": runtime_commit,
    "git_branch": runtime_branch,
    "git_dirty": runtime_dirty,
}, ensure_ascii=False))
PY
