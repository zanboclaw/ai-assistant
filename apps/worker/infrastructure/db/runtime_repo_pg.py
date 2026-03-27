from __future__ import annotations

from typing import Any, Callable

from psycopg2.extras import Json

from apps.api.infrastructure.db.connection import get_conn


def get_task_steps(cur, task_id: int) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT id, task_id, step_order, step_name, tool_name, status,
               input_payload, output_payload, output_data, error_message, run_if, skip_if, retry_count, max_retries, error_strategy,
               created_at, updated_at
        FROM task_steps
        WHERE task_id = %s
        ORDER BY step_order ASC;
        """,
        (task_id,),
    )
    return list(cur.fetchall() or [])


def select_final_outputs_for_task(
    cur,
    task_id: int,
    fallback_outputs: list[str],
    *,
    parse_jsonish: Callable[[Any, Any], Any],
    get_task_steps_fn: Callable[[Any, int], list[dict[str, Any]]] = get_task_steps,
) -> list[str]:
    cur.execute(
        """
        SELECT deliverable_spec_json
        FROM task_runs
        WHERE id = %s;
        """,
        (task_id,),
    )
    task_row = cur.fetchone() or {}
    deliverable_spec = parse_jsonish(task_row.get("deliverable_spec_json"), {})
    deliverable_type = str((deliverable_spec or {}).get("deliverable_type") or "").strip()
    if deliverable_type not in {
        "copywriting_bundle",
        "direct_answer",
        "execution_result",
        "generated_content",
        "research_summary",
        "rewritten_text",
        "research_then_generate_bundle",
    }:
        return fallback_outputs

    generated_outputs = [
        str(row.get("output_payload") or "").strip()
        for row in get_task_steps_fn(cur, task_id)
        if str(row.get("status") or "") == "completed"
        and str(row.get("tool_name") or "") == "generate_text"
        and str(row.get("output_payload") or "").strip()
    ]
    if generated_outputs:
        return [generated_outputs[-1]]
    return fallback_outputs


def update_task_delivery_records(
    cur,
    task_id: int,
    *,
    validation_report: dict[str, Any] | None = None,
    recovery_action: dict[str, Any] | None = None,
) -> None:
    cur.execute(
        """
        UPDATE task_runs
        SET validation_report_json = COALESCE(%s, validation_report_json),
            recovery_action_json = COALESCE(%s, recovery_action_json),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (
            Json(validation_report) if validation_report is not None else None,
            Json(recovery_action) if recovery_action is not None else None,
            task_id,
        ),
    )
    cur.connection.commit()


def count_task_audit_events(cur, task_id: int, event_type: str) -> int:
    cur.execute(
        """
        SELECT COUNT(*) AS count
        FROM audit_logs
        WHERE task_id = %s AND event_type = %s;
        """,
        (task_id, event_type),
    )
    row = cur.fetchone() or {}
    return int(row.get("count") or 0)


def find_first_step_order_by_tool(cur, task_id: int, tool_name: str) -> int | None:
    cur.execute(
        """
        SELECT step_order
        FROM task_steps
        WHERE task_id = %s AND tool_name = %s
        ORDER BY step_order ASC
        LIMIT 1;
        """,
        (task_id, tool_name),
    )
    row = cur.fetchone()
    return int(row["step_order"]) if row and row.get("step_order") is not None else None


__all__ = [
    "count_task_audit_events",
    "find_first_step_order_by_tool",
    "get_conn",
    "get_task_steps",
    "select_final_outputs_for_task",
    "update_task_delivery_records",
]
