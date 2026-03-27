from __future__ import annotations

from typing import Any, Callable


def create_structured_steps(
    cur,
    task_id: int,
    steps: list[dict[str, Any]],
    *,
    ensure_task_steps_columns: Callable[[Any], None],
    ensure_approvals_table: Callable[[Any], None],
    safe_json_dumps: Callable[[Any], str],
    default_max_retries_for_tool: Callable[[str], int],
) -> None:
    ensure_task_steps_columns(cur)
    ensure_approvals_table(cur)

    for idx, step in enumerate(steps, start=1):
        step_order = int(step.get("step_order") or idx)
        title = str(step.get("title") or f"步骤 {step_order}")
        tool_name = str(step.get("tool") or "").strip()
        input_payload = safe_json_dumps(step.get("input", {}))
        run_if = safe_json_dumps(step.get("run_if")) if step.get("run_if") is not None else None
        skip_if = safe_json_dumps(step.get("skip_if")) if step.get("skip_if") is not None else None
        error_strategy = str(step.get("error_strategy") or "fail").strip() or "fail"
        max_retries = int(step.get("max_retries") or default_max_retries_for_tool(tool_name))

        cur.execute(
            """
            INSERT INTO task_steps (
                task_id, step_order, step_name, tool_name, status,
                input_payload, output_payload, output_data, error_message, run_if, skip_if, retry_count, max_retries, error_strategy
            )
            VALUES (%s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s, %s, 0, %s, %s);
            """,
            (
                task_id,
                step_order,
                title,
                tool_name,
                input_payload,
                None,
                None,
                "",
                run_if,
                skip_if,
                max_retries,
                error_strategy,
            ),
        )


def create_legacy_steps(
    cur,
    task_id: int,
    step_names: list[str],
    *,
    ensure_task_steps_columns: Callable[[Any], None],
    ensure_approvals_table: Callable[[Any], None],
) -> None:
    ensure_task_steps_columns(cur)
    ensure_approvals_table(cur)

    for idx, step_name in enumerate(step_names, start=1):
        cur.execute(
            """
            INSERT INTO task_steps (
                task_id, step_order, step_name, tool_name, status,
                input_payload, output_payload, output_data, error_message, run_if, skip_if, retry_count, max_retries, error_strategy
            )
            VALUES (%s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s, %s, 0, %s, %s);
            """,
            (
                task_id,
                idx,
                step_name,
                None,
                None,
                None,
                None,
                "",
                None,
                None,
                0,
                "fail",
            ),
        )


def set_step_running(cur, task_id: int, step_order: int) -> None:
    cur.execute(
        """
        UPDATE task_steps
        SET status = 'running',
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = %s AND step_order = %s;
        """,
        (task_id, step_order),
    )


def set_step_retry_count(cur, task_id: int, step_order: int, retry_count: int) -> None:
    cur.execute(
        """
        UPDATE task_steps
        SET retry_count = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = %s AND step_order = %s;
        """,
        (retry_count, task_id, step_order),
    )


def set_step_result(
    cur,
    task_id: int,
    step_order: int,
    *,
    status: str,
    tool_name: str | None,
    input_payload: Any,
    output_payload: str | None,
    output_data: Any,
    error_message: str,
    error_strategy: str,
    safe_json_dumps: Callable[[Any], str],
) -> None:
    cur.execute(
        """
        UPDATE task_steps
        SET status = %s,
            tool_name = %s,
            input_payload = %s,
            output_payload = %s,
            output_data = %s,
            error_message = %s,
            error_strategy = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = %s AND step_order = %s;
        """,
        (
            status,
            tool_name,
            safe_json_dumps(input_payload) if input_payload is not None else None,
            output_payload,
            safe_json_dumps(output_data) if output_data is not None else None,
            error_message or "",
            error_strategy or "fail",
            task_id,
            step_order,
        ),
    )


__all__ = [
    "create_legacy_steps",
    "create_structured_steps",
    "set_step_result",
    "set_step_retry_count",
    "set_step_running",
]
