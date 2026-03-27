from __future__ import annotations

from typing import Any, Callable

from core.contracts.task_contracts import RecoveryActionContract


def trim_runtime_state_for_resume(
    *,
    resume_from: int,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
) -> tuple[dict[int, dict], dict[str, Any], list[str]]:
    trimmed_step_context = {
        int(step_order): value
        for step_order, value in step_context.items()
        if int(step_order) < int(resume_from)
    }
    trimmed_outputs = list(step_outputs[: max(0, int(resume_from) - 1)])
    return trimmed_step_context, dict(var_context), trimmed_outputs


def reset_task_for_auto_recovery(
    cur,
    *,
    task_id: int,
    user_input: str,
    resume_from: int,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    note: str,
    recovery_action: dict[str, Any],
    persist_task_runtime_state: Callable[..., None],
    update_task_trace_status: Callable[[Any, int], None],
    insert_audit_log: Callable[[Any, str, str, int | None, Any | None], None],
    enqueue_task: Callable[[int], None],
) -> None:
    trimmed_step_context, trimmed_var_context, trimmed_outputs = trim_runtime_state_for_resume(
        resume_from=resume_from,
        step_context=step_context,
        var_context=var_context,
        step_outputs=step_outputs,
    )
    cur.execute(
        """
        UPDATE task_steps
        SET status = 'pending',
            output_payload = NULL,
            output_data = NULL,
            error_message = '',
            retry_count = 0,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = %s
          AND step_order >= %s;
        """,
        (task_id, resume_from),
    )
    persist_task_runtime_state(
        cur,
        task_id,
        user_input,
        status="pending",
        current_step=resume_from,
        step_context=trimmed_step_context,
        var_context=trimmed_var_context,
        step_outputs=trimmed_outputs,
        task_error_message=None,
        checkpoint_error=note,
        result=None,
    )
    cur.execute(
        """
        UPDATE task_runs
        SET validation_report_json = NULL,
            recovery_action_json = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (task_id,),
    )
    update_task_trace_status(cur, task_id, status="pending", error_summary=note)
    insert_audit_log(
        cur,
        "task.auto_recovery_applied",
        "worker",
        task_id,
        {
            "resume_from": resume_from,
            "note": note,
            "recovery_action": recovery_action,
        },
    )
    cur.connection.commit()
    enqueue_task(task_id)


__all__ = ["RecoveryActionContract", "reset_task_for_auto_recovery", "trim_runtime_state_for_resume"]
