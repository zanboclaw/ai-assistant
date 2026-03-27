from __future__ import annotations

from typing import Any, Callable

from apps.worker.deliverable_runtime import append_execution_result_closure_steps


def assemble_task_success_result(
    cur,
    task_id: int,
    user_input: str,
    step_outputs: list[str],
    *,
    select_final_outputs_for_task: Callable[[Any, int, list[str]], list[str]],
    write_artifact: Callable[[int, str, list[str]], str],
) -> tuple[str, str]:
    final_outputs = select_final_outputs_for_task(cur, task_id, step_outputs)
    artifact_path = write_artifact(task_id, user_input, final_outputs)
    final_result = "\n\n".join(final_outputs) + f"\n\n产出文件：{artifact_path}"
    return artifact_path, final_result


__all__ = ["append_execution_result_closure_steps", "assemble_task_success_result"]
