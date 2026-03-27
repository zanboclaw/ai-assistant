from __future__ import annotations

from typing import Any

from fastapi import HTTPException


def list_tasks(
    cur,
    *,
    session_id: int | None = None,
    limit: int = 60,
    include_stage5_summary: bool = False,
    attach_task_display_fields,
    parse_maybe_json,
    fetch_task_agent_summary,
) -> list[dict[str, Any]]:
    where_sql = ""
    params: tuple[Any, ...] = ()
    if session_id is not None:
        cur.execute("SELECT id FROM sessions WHERE id = %s;", (session_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Session not found")
        where_sql = "WHERE session_id = %s"
        params = (session_id,)

    row_limit = max(1, min(int(limit or 60), 200))
    cur.execute(
        f"""
        SELECT
            id,
            session_id,
            created_by_actor,
            user_input,
            status,
            result,
            error_message,
            current_step,
            checkpoint_path,
            runtime_overrides,
            task_intent_json,
            deliverable_spec_json,
            validation_report_json,
            recovery_action_json,
            created_at,
            updated_at
        FROM task_runs
        {where_sql}
        ORDER BY id DESC;
        """,
        params,
    )
    rows = list(cur.fetchall() or [])[:row_limit]
    for row in rows:
        attach_task_display_fields(row)
        row["task_intent"] = parse_maybe_json(row.get("task_intent_json")) or {}
        row["deliverable_spec"] = parse_maybe_json(row.get("deliverable_spec_json")) or {}
        row["validation_report"] = parse_maybe_json(row.get("validation_report_json")) or {}
        row["recovery_action"] = parse_maybe_json(row.get("recovery_action_json")) or {}
        row.pop("task_intent_json", None)
        row.pop("deliverable_spec_json", None)
        row.pop("validation_report_json", None)
        row.pop("recovery_action_json", None)
        if include_stage5_summary:
            row["stage5"] = fetch_task_agent_summary(cur, int(row["id"]))
    return rows
