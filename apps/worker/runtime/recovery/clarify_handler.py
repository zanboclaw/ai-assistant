from __future__ import annotations

from typing import Any, Callable

from apps.api.task_control_runtime import reset_task_for_clarification


def fail_task_for_missing_clarification(
    cur,
    task_id: int,
    user_input: str,
    *,
    task_intent: dict[str, Any],
    deliverable_spec: dict[str, Any],
    ensure_task_trace: Callable[[Any, int, str], None],
    build_clarification_required_validation_report: Callable[..., dict[str, Any]],
    build_clarification_required_recovery_action: Callable[..., dict[str, Any]],
    build_clarification_required_message: Callable[..., str],
    update_task_delivery_records: Callable[..., None],
    persist_task_runtime_state: Callable[..., None],
    update_task_trace_status: Callable[[Any, int], None],
    insert_audit_log: Callable[[Any, str, str, int | None, Any | None], None],
) -> None:
    ensure_task_trace(cur, task_id, user_input)
    validation_report = build_clarification_required_validation_report(
        user_input,
        task_intent=task_intent,
        deliverable_spec=deliverable_spec,
    )
    recovery_action = build_clarification_required_recovery_action(
        task_intent=task_intent,
        deliverable_spec=deliverable_spec,
    )
    result_message = build_clarification_required_message(
        task_intent=task_intent,
        deliverable_spec=deliverable_spec,
    )
    update_task_delivery_records(
        cur,
        task_id,
        validation_report=validation_report,
        recovery_action=recovery_action,
    )
    persist_task_runtime_state(
        cur,
        task_id,
        user_input,
        status="waiting_clarification",
        current_step=None,
        step_context={},
        var_context={},
        step_outputs=[],
        task_error_message=str(recovery_action.get("summary") or "").strip(),
        checkpoint_error=str(recovery_action.get("summary") or "").strip(),
        result=result_message,
    )
    update_task_trace_status(
        cur,
        task_id,
        status="waiting_clarification",
        error_summary=str(recovery_action.get("summary") or "").strip(),
    )
    insert_audit_log(
        cur,
        "task.clarification_required",
        "worker",
        task_id,
        {
            "task_intent": task_intent,
            "deliverable_spec": deliverable_spec,
            "recovery_action": recovery_action,
        },
    )
    cur.connection.commit()


__all__ = ["fail_task_for_missing_clarification", "reset_task_for_clarification"]
