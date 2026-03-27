from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def checkpoint_file_for_task(task_id: int, *, checkpoint_dir: Path) -> Path:
    return checkpoint_dir / f"task_{task_id}.json"


def build_checkpoint_payload(
    *,
    status: str,
    current_step: int | None,
    error: str = "",
    task_id: int | None = None,
    user_input: str = "",
    step_context: dict[int, dict[str, Any]] | None = None,
    var_context: dict[str, Any] | None = None,
    step_outputs: list[str] | None = None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": status,
        "current_step": current_step,
        "error": error,
    }
    if task_id is not None:
        payload.update(
            {
                "task_id": task_id,
                "user_input": user_input,
                "step_context": step_context or {},
                "var_context": var_context or {},
                "step_outputs": list(step_outputs or []),
                "updated_at": updated_at or datetime.now(timezone.utc).isoformat(),
            }
        )
    return payload


def write_checkpoint(
    cur,
    task_id: int,
    user_input: str,
    status: str,
    current_step: int | None,
    step_context: dict[int, dict[str, Any]],
    var_context: dict[str, Any],
    step_outputs: list[str],
    last_error: str = "",
    *,
    checkpoint_dir: Path,
    update_task_progress,
) -> str:
    checkpoint_path = checkpoint_file_for_task(task_id, checkpoint_dir=checkpoint_dir)
    payload = build_checkpoint_payload(
        task_id=task_id,
        user_input=user_input,
        status=status,
        current_step=current_step,
        error=last_error,
        step_context=step_context,
        var_context=var_context,
        step_outputs=step_outputs,
    )
    checkpoint_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    update_task_progress(cur, task_id, current_step=current_step, checkpoint_path=str(checkpoint_path))
    return str(checkpoint_path)
