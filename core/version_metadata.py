from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "version.json"


def _run_git_command(args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(ROOT),
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return ""
    return completed.stdout.strip()


@lru_cache(maxsize=1)
def load_version_file() -> dict[str, Any]:
    try:
        return json.loads(VERSION_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_runtime_version_metadata() -> dict[str, Any]:
    version_payload = load_version_file()
    git_commit = os.environ.get("APP_GIT_COMMIT", "").strip() or _run_git_command(["rev-parse", "HEAD"])
    git_branch = os.environ.get("APP_GIT_BRANCH", "").strip() or _run_git_command(["rev-parse", "--abbrev-ref", "HEAD"])
    git_dirty = (os.environ.get("APP_GIT_DIRTY", "").strip() or _run_git_command(["status", "--porcelain"])).strip()
    build_timestamp = os.environ.get("APP_BUILD_TIMESTAMP", "").strip()
    current_version = str(version_payload.get("current_version") or "").strip()
    updated_at = str(version_payload.get("updated_at") or "").strip()
    repository = str(version_payload.get("repository") or "").strip()
    summary = str(version_payload.get("summary") or "").strip()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repository": repository,
        "current_version": current_version,
        "version_updated_at": updated_at,
        "build_timestamp": build_timestamp,
        "git_commit": git_commit,
        "git_short_commit": git_commit[:12] if git_commit else "",
        "git_branch": git_branch,
        "git_dirty": bool(git_dirty),
        "summary": summary,
    }
