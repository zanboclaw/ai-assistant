from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Header, HTTPException


def build_task_replay_payload(
    cur,
    task_id: int,
    *,
    ensure_trace_tables: Callable[[Any], None],
    parse_maybe_json: Callable[[Any], Any],
) -> dict[str, Any]:
    ensure_trace_tables(cur)
    cur.execute(
        """
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
            created_at,
            updated_at
        FROM task_runs
        WHERE id = %s;
        """,
        (task_id,),
    )
    task_row = cur.fetchone()
    if not task_row:
        raise HTTPException(status_code=404, detail="Task not found")
    task_row["runtime_overrides"] = parse_maybe_json(task_row.get("runtime_overrides")) or {}

    cur.execute(
        """
        SELECT *
        FROM task_traces
        WHERE task_run_id = %s
        ORDER BY id DESC
        LIMIT 1;
        """,
        (task_id,),
    )
    task_trace = cur.fetchone()

    cur.execute(
        """
        SELECT
            id,
            task_id,
            step_order,
            step_name,
            tool_name,
            status,
            input_payload,
            output_payload,
            output_data,
            error_message,
            run_if,
            skip_if,
            retry_count,
            max_retries,
            error_strategy,
            created_at,
            updated_at
        FROM task_steps
        WHERE task_id = %s
        ORDER BY step_order ASC;
        """,
        (task_id,),
    )
    step_rows = list(cur.fetchall())

    cur.execute(
        """
        SELECT *
        FROM step_traces
        WHERE task_run_id = %s
        ORDER BY step_order ASC, id ASC;
        """,
        (task_id,),
    )
    step_traces = list(cur.fetchall())

    cur.execute(
        """
        SELECT *
        FROM model_traces
        WHERE task_run_id = %s
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    model_traces = list(cur.fetchall())

    cur.execute(
        """
        SELECT *
        FROM tool_traces
        WHERE task_run_id = %s
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    tool_traces = list(cur.fetchall())

    cur.execute(
        """
        SELECT *
        FROM skill_traces
        WHERE task_run_id = %s
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    skill_traces = list(cur.fetchall())

    cur.execute(
        """
        SELECT *
        FROM retrieval_traces
        WHERE task_run_id = %s
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    retrieval_traces = list(cur.fetchall())

    cur.execute(
        """
        SELECT
            id,
            task_id,
            step_order,
            step_name,
            tool_name,
            input_payload,
            reason,
            status,
            decision_note,
            created_at,
            updated_at,
            decided_at
        FROM approvals
        WHERE task_id = %s
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    approvals = list(cur.fetchall())

    step_trace_map: dict[int, list[dict[str, Any]]] = {}
    model_trace_map: dict[int, list[dict[str, Any]]] = {}
    tool_trace_map: dict[int, list[dict[str, Any]]] = {}
    skill_trace_map: dict[int, list[dict[str, Any]]] = {}
    retrieval_trace_map: dict[int, list[dict[str, Any]]] = {}
    approval_map: dict[int, list[dict[str, Any]]] = {}

    for item in step_traces:
        step_trace_map.setdefault(int(item.get("task_step_id") or 0), []).append(item)
    for item in model_traces:
        model_trace_map.setdefault(int(item.get("task_step_id") or 0), []).append(item)
    for item in tool_traces:
        tool_trace_map.setdefault(int(item.get("task_step_id") or 0), []).append(item)
    for item in skill_traces:
        skill_trace_map.setdefault(int(item.get("task_step_id") or 0), []).append(item)
    for item in retrieval_traces:
        retrieval_trace_map.setdefault(int(item.get("task_step_id") or 0), []).append(item)
    for item in approvals:
        approval_map.setdefault(int(item.get("step_order") or 0), []).append(
            {
                **item,
                "input_payload": parse_maybe_json(item.get("input_payload")),
            }
        )

    replay_steps: list[dict[str, Any]] = []
    for step in step_rows:
        step_id = int(step["id"])
        step_order = int(step.get("step_order") or 0)
        parsed_input = parse_maybe_json(step.get("input_payload"))
        parsed_output_data = parse_maybe_json(step.get("output_data"))
        parsed_run_if = parse_maybe_json(step.get("run_if"))
        parsed_skip_if = parse_maybe_json(step.get("skip_if"))
        step_skill_traces = skill_trace_map.get(step_id, [])
        uses_skill = bool(step_skill_traces) or bool((task_row["runtime_overrides"] or {}).get("skill_invocation"))
        replay_steps.append(
            {
                "task_step_id": step_id,
                "step_order": step_order,
                "step_name": step.get("step_name") or f"步骤 {step_order}",
                "tool_name": step.get("tool_name") or "",
                "status": step.get("status") or "",
                "input_payload": parsed_input,
                "output_payload": step.get("output_payload"),
                "output_data": parsed_output_data,
                "error_message": step.get("error_message") or "",
                "run_if": parsed_run_if,
                "skip_if": parsed_skip_if,
                "retry_count": int(step.get("retry_count") or 0),
                "max_retries": int(step.get("max_retries") or 0),
                "error_strategy": step.get("error_strategy") or "fail",
                "created_at": step.get("created_at"),
                "updated_at": step.get("updated_at"),
                "approvals": approval_map.get(step_order, []),
                "traces": {
                    "step_traces": step_trace_map.get(step_id, []),
                    "model_traces": model_trace_map.get(step_id, []),
                    "tool_traces": tool_trace_map.get(step_id, []),
                    "skill_traces": step_skill_traces,
                    "retrieval_traces": retrieval_trace_map.get(step_id, []),
                },
                "trace_counts": {
                    "step": len(step_trace_map.get(step_id, [])),
                    "model": len(model_trace_map.get(step_id, [])),
                    "tool": len(tool_trace_map.get(step_id, [])),
                    "skill": len(step_skill_traces),
                    "retrieval": len(retrieval_trace_map.get(step_id, [])),
                },
                "replay_hints": {
                    "uses_skill": uses_skill,
                    "has_input_payload": parsed_input is not None,
                    "has_output_payload": bool(step.get("output_payload")),
                    "has_output_data": parsed_output_data is not None,
                    "approval_blocked": any(item.get("status") == "pending" for item in approval_map.get(step_order, [])),
                },
            }
        )

    return {
        "task": task_row,
        "task_trace": task_trace,
        "summary": {
            "mode": "read_only_trace_replay_v1",
            "plan_source": (task_trace or {}).get("plan_source") or "",
            "task_status": task_row.get("status") or "",
            "step_count": len(replay_steps),
            "completed_step_count": sum(1 for item in replay_steps if item.get("status") == "completed"),
            "failed_step_count": sum(1 for item in replay_steps if item.get("status") == "failed"),
            "waiting_approval_count": sum(1 for item in replay_steps if item.get("status") == "waiting_approval"),
            "waiting_clarification_count": sum(1 for item in replay_steps if item.get("status") == "waiting_clarification"),
            "model_trace_count": len(model_traces),
            "tool_trace_count": len(tool_traces),
            "skill_trace_count": len(skill_traces),
            "retrieval_trace_count": len(retrieval_traces),
            "has_explicit_skill": bool((task_row["runtime_overrides"] or {}).get("skill_invocation")),
        },
        "steps": replay_steps,
    }


def register_task_query_routes(
    *,
    get_conn: Callable[[], Any],
    require_actor_permission: Callable[[Any, str | None, str], Any],
    ensure_agent_tables: Callable[[Any], None],
    ensure_evaluator_tables: Callable[[Any], None],
    ensure_trace_tables: Callable[[Any], None],
    attach_task_display_fields: Callable[[dict[str, Any]], dict[str, Any]],
    parse_maybe_json: Callable[[Any], Any],
    fetch_latest_evaluator_for_task: Callable[[Any, int], dict[str, Any] | None],
    fetch_task_agent_summary: Callable[[Any, int], dict[str, Any]],
):
    router = APIRouter()

    @router.get("/tasks/{task_id}")
    def get_task(task_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        ensure_agent_tables(cur)
        ensure_evaluator_tables(cur)

        cur.execute(
            """
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
            WHERE id = %s;
            """,
            (task_id,),
        )
        row = cur.fetchone()

        if row:
            attach_task_display_fields(row)
            row["task_intent"] = parse_maybe_json(row.get("task_intent_json")) or {}
            row["deliverable_spec"] = parse_maybe_json(row.get("deliverable_spec_json")) or {}
            row["validation_report"] = parse_maybe_json(row.get("validation_report_json")) or {}
            row["recovery_action"] = parse_maybe_json(row.get("recovery_action_json")) or {}
            row.pop("task_intent_json", None)
            row.pop("deliverable_spec_json", None)
            row.pop("validation_report_json", None)
            row.pop("recovery_action_json", None)
            latest_evaluator = fetch_latest_evaluator_for_task(cur, task_id)
            row["stage5"] = fetch_task_agent_summary(cur, task_id)
            row["latest_evaluator"] = latest_evaluator
            row["latest_workflow_proposal"] = (latest_evaluator or {}).get("workflow_proposal") or {}

        cur.close()
        conn.close()

        if not row:
            raise HTTPException(status_code=404, detail="Task not found")

        return row

    @router.get("/tasks/{task_id}/steps")
    def get_task_steps(task_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")

        cur.execute("SELECT id FROM task_runs WHERE id = %s;", (task_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail="Task not found")

        cur.execute(
            """
            SELECT
                id,
                task_id,
                step_order,
                step_name,
                tool_name,
                status,
                input_payload,
                output_payload,
                output_data,
                error_message,
                run_if,
                skip_if,
                retry_count,
                max_retries,
                error_strategy,
                created_at,
                updated_at
            FROM task_steps
            WHERE task_id = %s
            ORDER BY step_order ASC;
            """,
            (task_id,),
        )
        rows = cur.fetchall()

        cur.close()
        conn.close()
        return rows

    @router.get("/tasks/{task_id}/traces")
    def get_task_traces(task_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        ensure_trace_tables(cur)

        cur.execute("SELECT id FROM task_runs WHERE id = %s;", (task_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail="Task not found")

        cur.execute(
            """
            SELECT *
            FROM task_traces
            WHERE task_run_id = %s
            ORDER BY id DESC
            LIMIT 1;
            """,
            (task_id,),
        )
        task_trace = cur.fetchone()

        cur.execute(
            """
            SELECT *
            FROM step_traces
            WHERE task_run_id = %s
            ORDER BY step_order ASC, id ASC;
            """,
            (task_id,),
        )
        step_traces = list(cur.fetchall())

        cur.execute(
            """
            SELECT *
            FROM model_traces
            WHERE task_run_id = %s
            ORDER BY id ASC;
            """,
            (task_id,),
        )
        model_traces = list(cur.fetchall())

        cur.execute(
            """
            SELECT *
            FROM tool_traces
            WHERE task_run_id = %s
            ORDER BY id ASC;
            """,
            (task_id,),
        )
        tool_traces = list(cur.fetchall())

        cur.execute(
            """
            SELECT *
            FROM skill_traces
            WHERE task_run_id = %s
            ORDER BY id ASC;
            """,
            (task_id,),
        )
        skill_traces = list(cur.fetchall())

        cur.execute(
            """
            SELECT *
            FROM retrieval_traces
            WHERE task_run_id = %s
            ORDER BY id ASC;
            """,
            (task_id,),
        )
        retrieval_traces = list(cur.fetchall())

        cur.close()
        conn.close()

        return {
            "task_id": task_id,
            "task_trace": task_trace,
            "step_traces": step_traces,
            "model_traces": model_traces,
            "tool_traces": tool_traces,
            "skill_traces": skill_traces,
            "retrieval_traces": retrieval_traces,
        }

    @router.get("/tasks/{task_id}/replay")
    def get_task_replay(task_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        payload = build_task_replay_payload(
            cur,
            task_id,
            ensure_trace_tables=ensure_trace_tables,
            parse_maybe_json=parse_maybe_json,
        )
        cur.close()
        conn.close()
        return payload

    @router.get("/tasks/{task_id}/steps/{step_id}/traces")
    def get_task_step_traces(
        task_id: int,
        step_id: int,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        ensure_trace_tables(cur)

        cur.execute("SELECT id FROM task_runs WHERE id = %s;", (task_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail="Task not found")

        cur.execute(
            """
            SELECT id, task_id, step_order, step_name, tool_name, status
            FROM task_steps
            WHERE id = %s AND task_id = %s;
            """,
            (step_id, task_id),
        )
        step_row = cur.fetchone()
        if not step_row:
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail="Task step not found")

        cur.execute(
            """
            SELECT *
            FROM step_traces
            WHERE task_run_id = %s AND task_step_id = %s
            ORDER BY id ASC;
            """,
            (task_id, step_id),
        )
        step_traces = list(cur.fetchall())

        cur.execute(
            """
            SELECT *
            FROM model_traces
            WHERE task_run_id = %s AND task_step_id = %s
            ORDER BY id ASC;
            """,
            (task_id, step_id),
        )
        model_traces = list(cur.fetchall())

        cur.execute(
            """
            SELECT *
            FROM tool_traces
            WHERE task_run_id = %s AND task_step_id = %s
            ORDER BY id ASC;
            """,
            (task_id, step_id),
        )
        tool_traces = list(cur.fetchall())

        cur.execute(
            """
            SELECT *
            FROM skill_traces
            WHERE task_run_id = %s AND task_step_id = %s
            ORDER BY id ASC;
            """,
            (task_id, step_id),
        )
        skill_traces = list(cur.fetchall())

        cur.execute(
            """
            SELECT *
            FROM retrieval_traces
            WHERE task_run_id = %s AND task_step_id = %s
            ORDER BY id ASC;
            """,
            (task_id, step_id),
        )
        retrieval_traces = list(cur.fetchall())

        cur.close()
        conn.close()

        return {
            "task_id": task_id,
            "step": step_row,
            "step_traces": step_traces,
            "model_traces": model_traces,
            "tool_traces": tool_traces,
            "skill_traces": skill_traces,
            "retrieval_traces": retrieval_traces,
        }

    @router.get("/tasks/{task_id}/checkpoint")
    def get_task_checkpoint(task_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        cur.execute(
            """
            SELECT id, checkpoint_path
            FROM task_runs
            WHERE id = %s;
            """,
            (task_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row:
            raise HTTPException(status_code=404, detail="Task not found")

        checkpoint_path = str(row.get("checkpoint_path") or "").strip()
        if not checkpoint_path:
            raise HTTPException(status_code=404, detail="Checkpoint not found")

        path = Path(checkpoint_path)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Checkpoint file missing")

        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Checkpoint unreadable: {exc}") from exc

    return router
