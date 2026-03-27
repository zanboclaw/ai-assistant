from __future__ import annotations

from typing import Any


def build_task_workspace(task_row: dict[str, Any], *, steps: list[dict[str, Any]] | None = None, checkpoint: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "task": task_row,
        "steps": list(steps or []),
        "checkpoint": dict(checkpoint or {}),
    }

