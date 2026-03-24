from __future__ import annotations

import hashlib
import threading
import uuid
from typing import Any

_trace_runtime_context = threading.local()


def set_current_trace_context(
    *,
    task_id: int | None = None,
    step_id: int | None = None,
    step_trace_id: int | None = None,
):
    _trace_runtime_context.task_id = task_id
    _trace_runtime_context.step_id = step_id
    _trace_runtime_context.step_trace_id = step_trace_id


def clear_current_trace_context():
    set_current_trace_context(task_id=None, step_id=None, step_trace_id=None)


def get_current_trace_context() -> dict[str, Any]:
    return {
        "task_id": getattr(_trace_runtime_context, "task_id", None),
        "step_id": getattr(_trace_runtime_context, "step_id", None),
        "step_trace_id": getattr(_trace_runtime_context, "step_trace_id", None),
    }


def ensure_task_trace(
    cur,
    task_id: int,
    user_input: str,
    *,
    ensure_trace_tables,
    trim_text,
    safe_json_dumps,
) -> int:
    ensure_trace_tables(cur)
    cur.execute("SELECT id FROM task_traces WHERE task_run_id = %s;", (task_id,))
    row = cur.fetchone()
    if row:
        cur.execute(
            """
            UPDATE task_traces
            SET updated_at = CURRENT_TIMESTAMP,
                input_summary = COALESCE(input_summary, %s)
            WHERE task_run_id = %s;
            """,
            (trim_text(user_input, 500), task_id),
        )
        return int(row["id"])
    trace_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO task_traces (
            trace_id, task_run_id, status, input_summary, metadata_json, started_at, updated_at
        )
        VALUES (%s, %s, 'running', %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        RETURNING id;
        """,
        (
            trace_id,
            task_id,
            trim_text(user_input, 500),
            safe_json_dumps({"trace_version": "p0-v1"}),
        ),
    )
    row = cur.fetchone()
    return int(row["id"])


def update_task_trace_status(
    cur,
    task_id: int,
    *,
    status: str,
    ensure_trace_tables,
    error_summary: str = "",
    plan_source: str | None = None,
):
    ensure_trace_tables(cur)
    if plan_source is None:
        cur.execute(
            """
            UPDATE task_traces
            SET status = %s,
                error_summary = %s,
                ended_at = CASE WHEN %s IN ('completed', 'failed', 'paused', 'waiting_approval') THEN CURRENT_TIMESTAMP ELSE ended_at END,
                updated_at = CURRENT_TIMESTAMP
            WHERE task_run_id = %s;
            """,
            (status, error_summary or "", status, task_id),
        )
    else:
        cur.execute(
            """
            UPDATE task_traces
            SET status = %s,
                error_summary = %s,
                plan_source = %s,
                ended_at = CASE WHEN %s IN ('completed', 'failed', 'paused', 'waiting_approval') THEN CURRENT_TIMESTAMP ELSE ended_at END,
                updated_at = CURRENT_TIMESTAMP
            WHERE task_run_id = %s;
            """,
            (status, error_summary or "", plan_source, status, task_id),
        )


def create_step_and_tool_trace(
    cur,
    *,
    task_id: int,
    task_step_id: int | None,
    step_order: int,
    step_name: str,
    tool_name: str,
    input_payload: Any,
    retry_count: int,
    max_retries: int,
    ensure_task_trace_fn,
    safe_json_dumps,
    json_hash,
) -> tuple[int, int]:
    task_trace_id = ensure_task_trace_fn(cur, task_id, "")
    step_trace_id = str(uuid.uuid4())
    tool_trace_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO step_traces (
            trace_id, task_trace_id, task_run_id, task_step_id, step_order, step_name, tool_name,
            status, input_snapshot, retry_count, max_retries, started_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'running', %s, %s, %s, CURRENT_TIMESTAMP)
        RETURNING id;
        """,
        (
            step_trace_id,
            task_trace_id,
            task_id,
            task_step_id,
            step_order,
            step_name,
            tool_name,
            safe_json_dumps(input_payload),
            retry_count,
            max_retries,
        ),
    )
    step_row = cur.fetchone()
    cur.execute(
        """
        INSERT INTO tool_traces (
            trace_id, task_run_id, task_step_id, step_trace_id, tool_name, tool_args_hash,
            status, input_snapshot, started_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, 'running', %s, CURRENT_TIMESTAMP)
        RETURNING id;
        """,
        (
            tool_trace_id,
            task_id,
            task_step_id,
            int(step_row["id"]),
            tool_name,
            json_hash(input_payload),
            safe_json_dumps(input_payload),
        ),
    )
    tool_row = cur.fetchone()
    cur.connection.commit()
    return int(step_row["id"]), int(tool_row["id"])


def complete_step_and_tool_trace(
    cur,
    *,
    step_trace_id: int | None,
    tool_trace_id: int | None,
    status: str,
    safe_json_dumps,
    trim_text,
    output_payload: Any = None,
    output_data: Any = None,
    error_summary: str = "",
    retry_count: int = 0,
):
    output_snapshot = {
        "output_payload": trim_text(output_payload, 2000),
        "output_data": output_data,
    }
    if step_trace_id:
        cur.execute(
            """
            UPDATE step_traces
            SET status = %s,
                output_snapshot = %s,
                error_summary = %s,
                retry_count = %s,
                ended_at = CURRENT_TIMESTAMP
            WHERE id = %s;
            """,
            (status, safe_json_dumps(output_snapshot), error_summary or "", retry_count, step_trace_id),
        )
    if tool_trace_id:
        cur.execute(
            """
            UPDATE tool_traces
            SET status = %s,
                output_snapshot = %s,
                error_summary = %s,
                ended_at = CURRENT_TIMESTAMP
            WHERE id = %s;
            """,
            (status, safe_json_dumps(output_snapshot), error_summary or "", tool_trace_id),
        )
    cur.connection.commit()


def record_model_trace(
    *,
    route_name: str,
    provider: str,
    model_name: str,
    prompt_version: str,
    prompt_text: str,
    get_current_trace_context_fn,
    get_conn,
    ensure_trace_tables,
    safe_json_dumps,
    trim_text,
    response_text: str = "",
    status: str = "completed",
    error_summary: str = "",
    metadata: dict[str, Any] | None = None,
):
    context = get_current_trace_context_fn()
    task_id = context.get("task_id")
    if not task_id:
        return
    conn = get_conn()
    cur = conn.cursor()
    try:
        ensure_trace_tables(cur)
        cur.execute(
            """
            INSERT INTO model_traces (
                trace_id, task_run_id, task_step_id, step_trace_id, route_name, provider, model_name,
                prompt_version, prompt_hash, status, request_excerpt, response_excerpt, error_summary,
                metadata_json, started_at, ended_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
            """,
            (
                str(uuid.uuid4()),
                task_id,
                context.get("step_id"),
                context.get("step_trace_id"),
                route_name,
                provider,
                model_name,
                prompt_version,
                hashlib.sha256((prompt_text or "").encode("utf-8")).hexdigest(),
                status,
                trim_text(prompt_text, 1200),
                trim_text(response_text, 1500),
                error_summary or "",
                safe_json_dumps(metadata or {}),
            ),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def create_skill_trace(
    cur,
    *,
    task_id: int,
    skill_id: str,
    skill_version: str,
    input_snapshot: Any,
    metadata: dict[str, Any] | None = None,
    ensure_trace_tables,
    safe_json_dumps,
) -> int:
    ensure_trace_tables(cur)
    cur.execute(
        """
        INSERT INTO skill_traces (
            trace_id, task_run_id, skill_id, skill_version, status, input_snapshot, metadata_json, started_at
        )
        VALUES (%s, %s, %s, %s, 'running', %s, %s, CURRENT_TIMESTAMP)
        RETURNING id;
        """,
        (
            str(uuid.uuid4()),
            task_id,
            skill_id,
            skill_version,
            safe_json_dumps(input_snapshot),
            safe_json_dumps(metadata or {}),
        ),
    )
    row = cur.fetchone()
    cur.connection.commit()
    return int(row["id"])


def complete_skill_trace(
    cur,
    *,
    skill_trace_id: int | None,
    status: str,
    safe_json_dumps,
    output_snapshot: Any = None,
    error_summary: str = "",
):
    if not skill_trace_id:
        return
    cur.execute(
        """
        UPDATE skill_traces
        SET status = %s,
            output_snapshot = %s,
            error_summary = %s,
            ended_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (status, safe_json_dumps(output_snapshot), error_summary or "", skill_trace_id),
    )
    cur.connection.commit()
