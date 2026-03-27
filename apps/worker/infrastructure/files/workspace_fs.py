from __future__ import annotations

from pathlib import Path


def ensure_workspace(root: str, task_id: int) -> Path:
    workspace = Path(root).resolve() / "workspace" / f"task_{int(task_id)}"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace

