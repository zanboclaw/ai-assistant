from __future__ import annotations

from typing import Any, Callable


def persist_task_runtime_state(
    cur,
    task_id: int,
    user_input: str,
    status: str,
    current_step: int | None,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    task_error_message: str | None,
    checkpoint_error: str,
    *,
    update_task_status: Callable[[Any, int, str, str | None, str | None], None],
    write_checkpoint: Callable[[Any, int, str, str, int | None, dict[int, dict], dict[str, Any], list[str], str], None],
    result: str | None = None,
    update_status_row: bool = True,
):
    if update_status_row:
        update_task_status(cur, task_id, status, result, task_error_message)
    write_checkpoint(
        cur,
        task_id,
        user_input,
        status,
        current_step,
        step_context,
        var_context,
        step_outputs,
        checkpoint_error,
    )
    cur.connection.commit()


def finalize_task_success(
    cur,
    task_id: int,
    user_input: str,
    step_outputs: list[str],
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    *,
    assemble_task_success_result: Callable[[Any, int, str, list[str]], tuple[str, str]],
    validate_task_deliverable: Callable[[Any, int], tuple[dict[str, Any], dict[str, Any]]],
    update_task_delivery_records: Callable[[Any, int], None],
    insert_audit_log: Callable[[Any, str, str, int | None, Any | None], None],
    count_task_audit_events: Callable[[Any, int, str], int],
    find_first_step_order_by_tool: Callable[[Any, int, str], int | None],
    reset_task_for_auto_recovery: Callable[..., None],
    auto_recovery_scheduled_exc_type: type[Exception],
    persist_task_runtime_state: Callable[..., None],
    update_task_trace_status: Callable[[Any, int], None],
    maybe_create_task_postrun_agent_records: Callable[[Any, int, str], None],
    capture_session_memory_for_completed_task: Callable[[Any, int, str, str], None],
    logger: Any,
) -> str:
    artifact_path, final_result = assemble_task_success_result(cur, task_id, user_input, step_outputs)
    validation_report, recovery_action = validate_task_deliverable(cur, task_id, user_input=user_input, final_result=final_result)
    update_task_delivery_records(
        cur,
        task_id,
        validation_report=validation_report,
        recovery_action=recovery_action,
    )
    insert_audit_log(
        cur,
        "task.validation_recorded",
        "worker",
        task_id,
        {
            "passed": bool(validation_report.get("passed")),
            "deliverable_type": validation_report.get("deliverable_type"),
            "recovery_action": recovery_action.get("action"),
        },
    )
    cur.connection.commit()

    if not bool(validation_report.get("passed")):
        validation_message = str(recovery_action.get("summary") or validation_report.get("summary") or "交付物校验失败").strip()
        action_key = str(recovery_action.get("action") or "").strip()
        auto_recovery_count = count_task_audit_events(cur, task_id, "task.auto_recovery_applied")
        if action_key == "retry_generate" and auto_recovery_count < 1:
            resume_from = find_first_step_order_by_tool(cur, task_id, "generate_text") or max(1, len(step_outputs))
            auto_note = f"auto recovery scheduled: {action_key}"
            reset_task_for_auto_recovery(
                cur,
                task_id=task_id,
                user_input=user_input,
                resume_from=resume_from,
                step_context=step_context,
                var_context=var_context,
                step_outputs=step_outputs,
                note=auto_note,
                recovery_action=recovery_action,
            )
            logger.info(
                "task auto recovery scheduled id=%s action=%s resume_from=%s",
                task_id,
                action_key,
                resume_from,
            )
            raise auto_recovery_scheduled_exc_type(auto_note)

        persist_task_runtime_state(
            cur,
            task_id,
            user_input,
            status="failed",
            current_step=None,
            step_context=step_context,
            var_context=var_context,
            step_outputs=step_outputs,
            task_error_message=validation_message,
            checkpoint_error=validation_message,
            result=final_result,
        )
        update_task_trace_status(cur, task_id, status="failed", error_summary=validation_message)
        insert_audit_log(
            cur,
            "task.validation_failed",
            "worker",
            task_id,
            {
                "failed_checks": [
                    item.get("name")
                    for item in list(validation_report.get("checks") or [])
                    if not bool((item or {}).get("passed"))
                ],
                "recovery_action": recovery_action,
            },
        )
        cur.connection.commit()
        try:
            postrun_cur = cur.connection.cursor()
            try:
                maybe_create_task_postrun_agent_records(postrun_cur, task_id, user_input)
            finally:
                postrun_cur.close()
        except Exception as exc:
            try:
                cur.connection.rollback()
            except Exception:
                pass
            logger.warning("task postrun agent capture failed task_id=%s error=%s", task_id, exc)
        logger.warning("task validation failed id=%s artifact=%s", task_id, artifact_path)
        return artifact_path

    persist_task_runtime_state(
        cur,
        task_id,
        user_input,
        status="completed",
        current_step=None,
        step_context=step_context,
        var_context=var_context,
        step_outputs=step_outputs,
        task_error_message=None,
        checkpoint_error="",
        result=final_result,
    )
    update_task_trace_status(cur, task_id, status="completed", error_summary="")
    try:
        capture_session_memory_for_completed_task(cur, task_id, user_input, final_result)
    except Exception as exc:
        try:
            cur.connection.rollback()
        except Exception:
            pass
        logger.warning("session memory auto capture failed task_id=%s error=%s", task_id, exc)
    try:
        postrun_cur = cur.connection.cursor()
        try:
            maybe_create_task_postrun_agent_records(postrun_cur, task_id, user_input)
        finally:
            postrun_cur.close()
    except Exception as exc:
        try:
            cur.connection.rollback()
        except Exception:
            pass
        logger.warning("task postrun agent capture failed task_id=%s error=%s", task_id, exc)
    logger.info("task completed id=%s artifact=%s", task_id, artifact_path)
    return artifact_path


def finalize_task_failure(
    cur,
    task_id: int,
    user_input: str,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    err: str,
    *,
    build_runtime_failure_validation_report: Callable[[str], dict[str, Any]],
    build_runtime_failure_recovery_action: Callable[[str], dict[str, Any]],
    update_task_delivery_records: Callable[..., None],
    persist_task_runtime_state: Callable[..., None],
    update_task_trace_status: Callable[[Any, int], None],
    insert_audit_log: Callable[[Any, str, str, int | None, Any | None], None],
    maybe_create_task_postrun_agent_records: Callable[[Any, int, str], None],
    logger: Any,
):
    try:
        cur.connection.rollback()
    except Exception:
        pass

    recovery_cur = cur.connection.cursor()
    try:
        validation_report = build_runtime_failure_validation_report(err)
        recovery_action = build_runtime_failure_recovery_action(err)
        update_task_delivery_records(
            recovery_cur,
            task_id,
            validation_report=validation_report,
            recovery_action=recovery_action,
        )
        persist_task_runtime_state(
            recovery_cur,
            task_id,
            user_input,
            status="failed",
            current_step=None,
            step_context=step_context,
            var_context=var_context,
            step_outputs=step_outputs,
            task_error_message=err,
            checkpoint_error=err,
        )
        update_task_trace_status(recovery_cur, task_id, status="failed", error_summary=err)
        insert_audit_log(
            recovery_cur,
            "task.runtime_failed",
            "worker",
            task_id,
            {
                "error": err[:300],
                "recovery_action": recovery_action,
            },
        )
        recovery_cur.connection.commit()
    finally:
        recovery_cur.close()

    try:
        postrun_cur = cur.connection.cursor()
        try:
            maybe_create_task_postrun_agent_records(postrun_cur, task_id, user_input)
        finally:
            postrun_cur.close()
    except Exception as exc:
        try:
            cur.connection.rollback()
        except Exception:
            pass
        logger.warning("task postrun agent capture failed task_id=%s error=%s", task_id, exc)


def start_task_execution(
    cur,
    task_id: int,
    user_input: str,
    *,
    ensure_task_trace: Callable[[Any, int, str], None],
    persist_task_runtime_state: Callable[..., None],
    update_task_trace_status: Callable[[Any, int], None],
):
    ensure_task_trace(cur, task_id, user_input)
    persist_task_runtime_state(
        cur,
        task_id,
        user_input,
        status="running",
        current_step=None,
        step_context={},
        var_context={},
        step_outputs=[],
        task_error_message=None,
        checkpoint_error="",
    )
    update_task_trace_status(cur, task_id, status="running", error_summary="")


def start_step_execution(
    cur,
    task_id: int,
    step_order: int,
    *,
    set_step_running: Callable[[Any, int, int], None],
    update_task_progress: Callable[[Any, int], None],
):
    set_step_running(cur, task_id, step_order)
    update_task_progress(cur, task_id, current_step=step_order)
    cur.connection.commit()


def record_legacy_step_result(
    cur,
    task_id: int,
    step_order: int,
    output_text: str,
    ok: bool,
    *,
    set_step_result: Callable[..., None],
):
    set_step_result(
        cur,
        task_id,
        step_order,
        status="completed" if ok else "failed",
        tool_name=None,
        input_payload=None,
        output_payload=output_text,
        output_data=None,
        error_message="" if ok else output_text,
        error_strategy="fail",
    )
    cur.connection.commit()


def persist_legacy_step_runtime_state(
    cur,
    task_id: int,
    user_input: str,
    step_order: int,
    output_text: str,
    step_outputs: list[str],
    *,
    persist_task_runtime_state: Callable[..., None],
):
    step_outputs.append(output_text)
    persist_task_runtime_state(
        cur,
        task_id,
        user_input,
        status="running",
        current_step=step_order,
        step_context={},
        var_context={},
        step_outputs=step_outputs,
        task_error_message=None,
        checkpoint_error="",
        update_status_row=False,
    )
