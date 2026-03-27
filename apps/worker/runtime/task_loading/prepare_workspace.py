from __future__ import annotations

from pathlib import Path


def prepare_workspace(task_id: int, *, root: str) -> Path:
    task_workspace = Path(root).resolve() / "workspace" / f"task_{int(task_id)}"
    task_workspace.mkdir(parents=True, exist_ok=True)
    return task_workspace

