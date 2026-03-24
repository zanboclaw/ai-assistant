from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import APIRouter, Header, HTTPException

from schemas import AgentBootstrapRequest, AgentExecuteRequest, AgentFinalizeRequest


def register_multi_agent_demo_routes(
    *,
    get_conn: Callable[[], Any],
    require_actor_permission: Callable[[Any, str | None, str], dict[str, Any]],
    ensure_agent_tables: Callable[[Any], None],
    build_task_display_user_input: Callable[[str, dict[str, Any]], str],
    parse_maybe_json: Callable[[Any], Any],
    multi_agent_protocol_version: str,
    create_agent_artifact: Callable[..., int],
    create_agent_run: Callable[..., int],
    create_agent_message: Callable[..., int],
    build_specialist_execution_request: Callable[..., dict[str, Any]],
    insert_audit_log: Callable[[Any, str, str, int | None, Any | None], None],
    logger: Any,
    safe_json_dumps: Callable[[Any], str],
    serialize_agent_artifact_row: Callable[[dict[str, Any]], dict[str, Any]],
    build_specialist_step_partitions: Callable[..., tuple[list[dict[str, Any]], list[list[dict[str, Any]]], dict[str, int]]],
    build_specialist_draft_payload: Callable[..., dict[str, Any]],
    enqueue_agent_run: Callable[[int], Any],
    resolve_reviewer_decision: Callable[..., tuple[str, str]],
    build_demo_review_criteria: Callable[..., dict[str, Any]],
    derive_evaluator_failure_profile: Callable[..., dict[str, Any]],
    build_workflow_proposal: Callable[..., dict[str, Any]],
    create_evaluator_run: Callable[..., int],
    serialize_workflow_proposal: Callable[..., dict[str, Any]],
):
    router = APIRouter()

    @router.post("/tasks/{task_id}/agent-runs/bootstrap-demo")
    def bootstrap_task_agent_runs(
        task_id: int,
        request: AgentBootstrapRequest,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        specialist_count = max(1, min(int(request.specialist_count or 2), 4))
        objective = request.objective.strip()
        note = request.note.strip()

        conn = get_conn()
        cur = conn.cursor()
        actor = require_actor_permission(cur, x_actor_name, "operate")
        ensure_agent_tables(cur)

        cur.execute(
            """
            SELECT id, user_input, status, session_id, runtime_overrides, created_at, updated_at
            FROM task_runs
            WHERE id = %s;
            """,
            (task_id,),
        )
        task_row = cur.fetchone()
        if not task_row:
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail="Task not found")

        cur.execute("SELECT COUNT(*) AS count FROM agent_runs WHERE task_run_id = %s;", (task_id,))
        existing_count = int(cur.fetchone()["count"])
        if existing_count > 0:
            cur.close()
            conn.close()
            raise HTTPException(status_code=409, detail="Task already has agent runs; bootstrap-demo is single-use per task")

        manager_objective = objective or build_task_display_user_input(
            str(task_row.get("user_input") or ""),
            parse_maybe_json(task_row.get("runtime_overrides")) or {},
        )
        plan_payload = {
            "protocol_version": multi_agent_protocol_version,
            "task_id": task_id,
            "task_status": task_row["status"],
            "objective": manager_objective,
            "fan_out_strategy": f"manager + {specialist_count} specialist" + (" + reviewer" if request.include_reviewer else ""),
            "fallback_strategy": "degrade_to_single_agent_or_escalate",
            "note": note,
        }
        manager_plan_artifact_id = create_agent_artifact(
            cur,
            task_id,
            None,
            "plan",
            "bootstrap demo manager plan",
            {
                **plan_payload,
                "subtasks": [
                    {
                        "role": "specialist",
                        "slot": index + 1,
                        "scope": f"子问题 {index + 1}",
                    }
                    for index in range(specialist_count)
                ],
            },
        )
        manager_run_id = create_agent_run(
            cur,
            task_id,
            "manager",
            "completed",
            brief_artifact_id=manager_plan_artifact_id,
            output_artifact_id=manager_plan_artifact_id,
            assigned_model="planning-default",
            assigned_tool_profile="manager-only",
            started=True,
            completed=True,
        )

        created_agent_run_ids = [manager_run_id]
        created_message_ids: list[int] = []
        created_artifact_ids = [manager_plan_artifact_id]
        specialist_run_ids: list[int] = []

        for index in range(specialist_count):
            slot = index + 1
            execution_request = build_specialist_execution_request(
                slot=slot,
                manager_objective=manager_objective,
                assigned_steps=[],
                plan_artifact_id=manager_plan_artifact_id,
                note=request.note.strip(),
            )
            brief_artifact_id = create_agent_artifact(
                cur,
                task_id,
                None,
                "brief",
                f"specialist-{slot} brief",
                {
                    "protocol_version": multi_agent_protocol_version,
                    "objective": manager_objective,
                    "scope": f"子问题 {slot}",
                    "constraints": ["遵守当前 task scope", "不要直接给最终结论"],
                    "success_criteria": [f"完成子问题 {slot} 的可交付草稿"],
                    "input_refs": [{"artifact_id": manager_plan_artifact_id, "label": "manager_plan"}],
                    "execution_request": execution_request,
                },
            )
            specialist_run_id = create_agent_run(
                cur,
                task_id,
                "specialist",
                "queued",
                parent_agent_run_id=manager_run_id,
                brief_artifact_id=brief_artifact_id,
                execution_mode="api_readonly_subtask_v1",
                execution_request={
                    **execution_request,
                    "evidence_refs": execution_request["evidence_refs"] + [{"artifact_id": brief_artifact_id, "label": "specialist_brief"}],
                },
                source_task_run_id=task_id,
                assigned_step_orders=[],
                assigned_model=f"specialist-default-{slot}",
                assigned_tool_profile="specialist-readonly",
            )
            specialist_run_ids.append(specialist_run_id)
            created_agent_run_ids.append(specialist_run_id)
            created_artifact_ids.append(brief_artifact_id)
            created_message_ids.append(
                create_agent_message(
                    cur,
                    task_id,
                    specialist_run_id,
                    "manager",
                    "specialist",
                    "brief",
                    {
                        "protocol_version": multi_agent_protocol_version,
                        "task_run_id": task_id,
                        "agent_run_id": specialist_run_id,
                        "sender_role": "manager",
                        "recipient_role": "specialist",
                        "slot": slot,
                        "brief_artifact_id": brief_artifact_id,
                        "execution_request": {
                            **execution_request,
                            "evidence_refs": execution_request["evidence_refs"] + [{"artifact_id": brief_artifact_id, "label": "specialist_brief"}],
                        },
                    },
                )
            )

        reviewer_run_id = None
        if request.include_reviewer:
            review_artifact_id = create_agent_artifact(
                cur,
                task_id,
                None,
                "review",
                "reviewer handoff placeholder",
                {
                    "protocol_version": multi_agent_protocol_version,
                    "objective": "在 specialist 草稿完成后独立审查 manager 汇总",
                    "decision": "pending",
                    "blocking_issues": [],
                    "follow_up_actions": ["等待 specialist draft", "等待 manager final candidate"],
                },
            )
            reviewer_run_id = create_agent_run(
                cur,
                task_id,
                "reviewer",
                "planned",
                parent_agent_run_id=manager_run_id,
                review_artifact_id=review_artifact_id,
                source_task_run_id=task_id,
                assigned_model="review-default",
                assigned_tool_profile="review-readonly",
            )
            created_agent_run_ids.append(reviewer_run_id)
            created_artifact_ids.append(review_artifact_id)
            created_message_ids.append(
                create_agent_message(
                    cur,
                    task_id,
                    reviewer_run_id,
                    "manager",
                    "reviewer",
                    "handoff",
                    {
                        "protocol_version": multi_agent_protocol_version,
                        "task_run_id": task_id,
                        "agent_run_id": reviewer_run_id,
                        "sender_role": "manager",
                        "recipient_role": "reviewer",
                        "depends_on_agent_run_ids": specialist_run_ids,
                        "review_status": "pending_inputs",
                    },
                )
            )

        insert_audit_log(
            cur,
            "agent.bootstrap_demo",
            actor["actor_name"],
            task_id,
            {
                "task_id": task_id,
                "manager_run_id": manager_run_id,
                "specialist_run_ids": specialist_run_ids,
                "reviewer_run_id": reviewer_run_id,
                "specialist_count": specialist_count,
                "include_reviewer": bool(request.include_reviewer),
                "objective": manager_objective,
            },
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.info(
            "agent bootstrap demo created task_id=%s manager_run_id=%s specialist_count=%s reviewer=%s actor=%s",
            task_id,
            manager_run_id,
            specialist_count,
            bool(request.include_reviewer),
            actor["actor_name"],
        )
        return {
            "message": "agent bootstrap demo created",
            "task_id": task_id,
            "manager_run_id": manager_run_id,
            "specialist_run_ids": specialist_run_ids,
            "reviewer_run_id": reviewer_run_id,
            "created_agent_run_count": len(created_agent_run_ids),
            "created_message_count": len(created_message_ids),
            "created_artifact_count": len(created_artifact_ids),
        }

    @router.post("/tasks/{task_id}/agent-runs/execute-demo")
    def execute_task_agent_runs(
        task_id: int,
        request: AgentExecuteRequest,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        note = request.note.strip()
        force_rerun = bool(request.force_rerun)

        conn = get_conn()
        cur = conn.cursor()
        actor = require_actor_permission(cur, x_actor_name, "operate")
        ensure_agent_tables(cur)

        cur.execute(
            """
            SELECT id, user_input, status, result, error_message, runtime_overrides, created_at, updated_at
            FROM task_runs
            WHERE id = %s;
            """,
            (task_id,),
        )
        task_row = cur.fetchone()
        if not task_row:
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail="Task not found")

        cur.execute(
            """
            SELECT id, task_run_id, parent_agent_run_id, role, status, attempt, brief_artifact_id,
                   output_artifact_id, review_artifact_id, execution_mode, execution_request_json,
                   source_task_run_id, assigned_step_orders_json, assigned_model, assigned_tool_profile,
                   error_summary, cost_tokens_in, cost_tokens_out, cost_usd_estimate,
                   created_at, updated_at, started_at, completed_at
            FROM agent_runs
            WHERE task_run_id = %s
            ORDER BY id ASC;
            """,
            (task_id,),
        )
        agent_rows = cur.fetchall()
        if not agent_rows:
            cur.close()
            conn.close()
            raise HTTPException(status_code=409, detail="Task has no agent runs; bootstrap-demo first")

        manager_row = next((row for row in agent_rows if row["role"] == "manager"), None)
        specialist_rows = [row for row in agent_rows if row["role"] == "specialist"]
        if not manager_row or not specialist_rows:
            cur.close()
            conn.close()
            raise HTTPException(status_code=409, detail="Task is missing manager or specialist agent runs")

        cur.execute(
            """
            SELECT step_order, step_name, status, tool_name, input_payload, output_payload, error_message
            FROM task_steps
            WHERE task_id = %s
            ORDER BY step_order ASC;
            """,
            (task_id,),
        )
        step_rows = cur.fetchall()
        cur.execute(
            """
            SELECT id, agent_run_id, artifact_type, summary, content_json, version, created_at
            FROM agent_artifacts
            WHERE task_run_id = %s
            ORDER BY id ASC;
            """,
            (task_id,),
        )
        artifact_rows = [serialize_agent_artifact_row(row) for row in cur.fetchall()]
        artifact_by_id = {int(item["id"]): item for item in artifact_rows}
        plan_artifact = next((item for item in artifact_rows if item["artifact_type"] == "plan"), None)

        manager_objective = build_task_display_user_input(
            str(task_row.get("user_input") or ""),
            parse_maybe_json(task_row.get("runtime_overrides")) or {},
        )
        step_outline, specialist_step_partitions, step_status_counts = build_specialist_step_partitions(
            step_rows=step_rows,
            specialist_count=len(specialist_rows),
            task_row=task_row,
        )

        created_artifact_ids: list[int] = []
        created_message_ids: list[int] = []
        executed_specialist_ids: list[int] = []
        skipped_specialist_ids: list[int] = []
        retried_specialist_ids: list[int] = []

        for index, specialist_row in enumerate(specialist_rows, start=1):
            existing_output_artifact_id = specialist_row.get("output_artifact_id")
            if existing_output_artifact_id and not force_rerun:
                skipped_specialist_ids.append(int(specialist_row["id"]))
                continue
            artifact_version = 1
            next_attempt = int(specialist_row.get("attempt") or 1)
            if existing_output_artifact_id:
                existing_output_artifact = artifact_by_id.get(int(existing_output_artifact_id))
                artifact_version = int((existing_output_artifact or {}).get("version") or 1) + 1
                next_attempt += 1
                retried_specialist_ids.append(int(specialist_row["id"]))
            assigned_steps = specialist_step_partitions[index - 1]
            execution_request = build_specialist_execution_request(
                slot=index,
                manager_objective=manager_objective,
                assigned_steps=assigned_steps,
                brief_artifact_id=specialist_row.get("brief_artifact_id"),
                plan_artifact_id=plan_artifact["id"] if plan_artifact else None,
                note=note,
                execution_mode="worker_readonly_v1",
            )
            cur.execute(
                """
                UPDATE agent_runs
                SET status = 'running',
                    execution_mode = %s,
                    execution_request_json = %s,
                    source_task_run_id = %s,
                    assigned_step_orders_json = %s,
                    started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                    completed_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
                """,
                (
                    "api_readonly_subtask_v1",
                    safe_json_dumps(execution_request),
                    task_id,
                    safe_json_dumps(execution_request.get("assigned_step_orders") or []),
                    specialist_row["id"],
                ),
            )
            created_message_ids.append(
                create_agent_message(
                    cur,
                    task_id,
                    specialist_row["id"],
                    "manager",
                    "specialist",
                    "handoff",
                    {
                        "protocol_version": multi_agent_protocol_version,
                        "task_run_id": task_id,
                        "subtask_type": "readonly_step_digest",
                        "execution_mode": "api_readonly_subtask_v1",
                        "assigned_step_orders": [int(step.get("step_order") or 0) for step in assigned_steps if int(step.get("step_order") or 0) > 0],
                        "manager_objective": manager_objective,
                        "note": note,
                        "force_rerun": force_rerun,
                        "execution_request": execution_request,
                    },
                )
            )
            created_message_ids.append(
                create_agent_message(
                    cur,
                    task_id,
                    specialist_row["id"],
                    "specialist",
                    "manager",
                    "progress",
                    {
                        "protocol_version": multi_agent_protocol_version,
                        "status": "running",
                        "execution_mode": "api_readonly_subtask_v1",
                        "subtask_type": "readonly_step_digest",
                        "assigned_step_orders": [int(step.get("step_order") or 0) for step in assigned_steps if int(step.get("step_order") or 0) > 0],
                        "summary": f"specialist-{index} started readonly subtask",
                    },
                )
            )
            draft_payload = build_specialist_draft_payload(
                slot=index,
                task_id=task_id,
                agent_run_id=int(specialist_row["id"]),
                manager_objective=manager_objective,
                task_row=task_row,
                step_outline=step_outline,
                assigned_steps=assigned_steps,
                plan_artifact_id=plan_artifact["id"] if plan_artifact else None,
                note=note,
                step_status_counts=step_status_counts,
                execution_request=execution_request,
            )
            draft_artifact_id = create_agent_artifact(
                cur,
                task_id,
                specialist_row["id"],
                "draft",
                f"specialist-{index} draft",
                draft_payload,
                version=artifact_version,
            )
            created_artifact_ids.append(draft_artifact_id)
            executed_specialist_ids.append(int(specialist_row["id"]))
            cur.execute(
                """
                UPDATE agent_runs
                SET status = 'completed',
                    attempt = %s,
                    output_artifact_id = %s,
                    execution_mode = %s,
                    execution_request_json = %s,
                    source_task_run_id = %s,
                    assigned_step_orders_json = %s,
                    error_summary = '',
                    started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                    completed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
                """,
                (
                    next_attempt,
                    draft_artifact_id,
                    "api_readonly_subtask_v1",
                    safe_json_dumps(execution_request),
                    task_id,
                    safe_json_dumps(execution_request.get("assigned_step_orders") or []),
                    specialist_row["id"],
                ),
            )
            created_message_ids.append(
                create_agent_message(
                    cur,
                    task_id,
                    specialist_row["id"],
                    "specialist",
                    "manager",
                    "result",
                    {
                        "protocol_version": multi_agent_protocol_version,
                        "status": "completed",
                        "artifact_ids": [draft_artifact_id],
                        "summary": f"specialist-{index} draft",
                        "needs_human_review": False,
                    },
                )
            )

        reviewer_row = next((row for row in agent_rows if row["role"] == "reviewer"), None)
        if reviewer_row and executed_specialist_ids:
            cur.execute(
                """
                UPDATE agent_runs
                SET status = CASE
                        WHEN status IN ('planned', 'queued') THEN 'queued'
                        ELSE status
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
                """,
                (reviewer_row["id"],),
            )
            created_message_ids.append(
                create_agent_message(
                    cur,
                    task_id,
                    reviewer_row["id"],
                    "manager",
                    "reviewer",
                    "handoff",
                    {
                        "protocol_version": multi_agent_protocol_version,
                        "task_run_id": task_id,
                        "review_status": "ready_for_review",
                        "depends_on_specialist_ids": executed_specialist_ids,
                        "summary": "specialist outputs ready for reviewer",
                    },
                )
            )

        insert_audit_log(
            cur,
            "agent.execute_demo",
            actor["actor_name"],
            task_id,
            {
                "task_id": task_id,
                "manager_run_id": int(manager_row["id"]),
                "executed_specialist_ids": executed_specialist_ids,
                "skipped_specialist_ids": skipped_specialist_ids,
                "retried_specialist_ids": retried_specialist_ids,
                "created_artifact_count": len(created_artifact_ids),
                "force_rerun": force_rerun,
            },
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.info(
            "agent execute demo completed task_id=%s executed_specialists=%s skipped_specialists=%s actor=%s",
            task_id,
            len(executed_specialist_ids),
            len(skipped_specialist_ids),
            actor["actor_name"],
        )
        return {
            "message": "agent execute demo completed",
            "task_id": task_id,
            "executed_specialist_ids": executed_specialist_ids,
            "skipped_specialist_ids": skipped_specialist_ids,
            "retried_specialist_ids": retried_specialist_ids,
            "created_message_count": len(created_message_ids),
            "created_artifact_count": len(created_artifact_ids),
            "execution_mode": "api_readonly_subtask_v1",
            "force_rerun": force_rerun,
        }

    @router.post("/tasks/{task_id}/agent-runs/execute-worker-demo")
    def execute_task_agent_runs_via_worker(
        task_id: int,
        request: AgentExecuteRequest,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        note = request.note.strip()
        force_rerun = bool(request.force_rerun)
        subtask_type = (request.subtask_type or "readonly_step_digest").strip() or "readonly_step_digest"
        if subtask_type not in {"readonly_step_digest", "readonly_source_snapshot", "readonly_task_snapshot"}:
            raise HTTPException(status_code=400, detail="subtask_type must be readonly_step_digest, readonly_source_snapshot, or readonly_task_snapshot")
        source_payload = {
            "kind": (request.source_kind or "").strip(),
            "path": (request.source_path or "").strip(),
            "json_path": (request.source_json_path or "").strip(),
            "dir_limit": max(1, min(int(request.dir_limit or 20), 200)),
        }
        if subtask_type == "readonly_source_snapshot":
            if source_payload["kind"] not in {"text_file", "json_file", "directory"}:
                raise HTTPException(status_code=400, detail="readonly_source_snapshot requires source_kind=text_file|json_file|directory")
            if not source_payload["path"]:
                raise HTTPException(status_code=400, detail="readonly_source_snapshot requires source_path")

        conn = get_conn()
        cur = conn.cursor()
        actor = require_actor_permission(cur, x_actor_name, "operate")
        ensure_agent_tables(cur)

        cur.execute(
            "SELECT id, user_input, status, runtime_overrides FROM task_runs WHERE id = %s;",
            (task_id,),
        )
        task_row = cur.fetchone()
        if not task_row:
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail="Task not found")

        cur.execute(
            """
            SELECT id, task_run_id, parent_agent_run_id, role, status, attempt, brief_artifact_id,
                   output_artifact_id, review_artifact_id, execution_mode, execution_request_json,
                   source_task_run_id, assigned_step_orders_json, assigned_model, assigned_tool_profile,
                   error_summary, cost_tokens_in, cost_tokens_out, cost_usd_estimate,
                   created_at, updated_at, started_at, completed_at
            FROM agent_runs
            WHERE task_run_id = %s
            ORDER BY id ASC;
            """,
            (task_id,),
        )
        agent_rows = cur.fetchall()
        manager_row = next((row for row in agent_rows if row["role"] == "manager"), None)
        specialist_rows = [row for row in agent_rows if row["role"] == "specialist"]
        if not manager_row or not specialist_rows:
            cur.close()
            conn.close()
            raise HTTPException(status_code=409, detail="Task is missing manager or specialist agent runs")

        cur.execute(
            """
            SELECT step_order, step_name, status, tool_name, input_payload, output_payload, error_message
            FROM task_steps
            WHERE task_id = %s
            ORDER BY step_order ASC;
            """,
            (task_id,),
        )
        step_rows = cur.fetchall()
        cur.execute(
            """
            SELECT id, agent_run_id, artifact_type, summary, content_json, version, created_at
            FROM agent_artifacts
            WHERE task_run_id = %s
            ORDER BY id ASC;
            """,
            (task_id,),
        )
        artifact_rows = [serialize_agent_artifact_row(row) for row in cur.fetchall()]
        plan_artifact = next((item for item in artifact_rows if item["artifact_type"] == "plan"), None)
        manager_objective = build_task_display_user_input(
            str(task_row.get("user_input") or ""),
            parse_maybe_json(task_row.get("runtime_overrides")) or {},
        )
        _, specialist_step_partitions, _ = build_specialist_step_partitions(
            step_rows=step_rows,
            specialist_count=len(specialist_rows),
            task_row=task_row,
        )

        queued_specialist_ids: list[int] = []
        skipped_specialist_ids: list[int] = []
        created_message_ids: list[int] = []
        retried_specialist_ids: list[int] = []
        for index, specialist_row in enumerate(specialist_rows, start=1):
            existing_output_artifact_id = specialist_row.get("output_artifact_id")
            if existing_output_artifact_id and not force_rerun:
                skipped_specialist_ids.append(int(specialist_row["id"]))
                continue
            if existing_output_artifact_id:
                retried_specialist_ids.append(int(specialist_row["id"]))
            assigned_steps = specialist_step_partitions[index - 1]
            execution_request = build_specialist_execution_request(
                slot=index,
                manager_objective=manager_objective,
                assigned_steps=assigned_steps,
                brief_artifact_id=specialist_row.get("brief_artifact_id"),
                plan_artifact_id=plan_artifact["id"] if plan_artifact else None,
                note=note,
                execution_mode="worker_readonly_v1",
                subtask_type=subtask_type,
                source=source_payload if subtask_type == "readonly_source_snapshot" else None,
            )
            cur.execute(
                """
                UPDATE agent_runs
                SET status = 'queued',
                    execution_mode = %s,
                    execution_request_json = %s,
                    source_task_run_id = %s,
                    assigned_step_orders_json = %s,
                    updated_at = CURRENT_TIMESTAMP,
                    completed_at = NULL
                WHERE id = %s;
                """,
                (
                    "worker_readonly_v1",
                    safe_json_dumps(execution_request),
                    task_id,
                    safe_json_dumps(execution_request.get("assigned_step_orders") or []),
                    specialist_row["id"],
                ),
            )
            created_message_ids.append(
                create_agent_message(
                    cur,
                    task_id,
                    specialist_row["id"],
                    "manager",
                    "specialist",
                    "handoff",
                    {
                        "protocol_version": multi_agent_protocol_version,
                        "task_run_id": task_id,
                        "execution_mode": "worker_readonly_v1",
                        "subtask_type": subtask_type,
                        "execution_request": execution_request,
                        "force_rerun": force_rerun,
                    },
                )
            )
            queued_specialist_ids.append(int(specialist_row["id"]))
            enqueue_agent_run(int(specialist_row["id"]))

        insert_audit_log(
            cur,
            "agent.execute_worker_demo",
            actor["actor_name"],
            task_id,
            {
                "task_id": task_id,
                "manager_run_id": int(manager_row["id"]),
                "queued_specialist_ids": queued_specialist_ids,
                "skipped_specialist_ids": skipped_specialist_ids,
                "retried_specialist_ids": retried_specialist_ids,
                "force_rerun": force_rerun,
            },
        )
        conn.commit()
        cur.close()
        conn.close()
        return {
            "message": "agent worker execute demo queued",
            "task_id": task_id,
            "queued_specialist_ids": queued_specialist_ids,
            "skipped_specialist_ids": skipped_specialist_ids,
            "retried_specialist_ids": retried_specialist_ids,
            "created_message_count": len(created_message_ids),
            "execution_mode": "worker_readonly_v1",
            "subtask_type": subtask_type,
            "execution_backend": "worker",
            "dispatch_mode": "worker_queue",
        }

    @router.post("/tasks/{task_id}/agent-runs/finalize-demo")
    def finalize_task_agent_runs(
        task_id: int,
        request: AgentFinalizeRequest,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        summary = request.summary.strip()
        note = request.note.strip()
        requested_reviewer_decision = request.reviewer_decision.strip().lower() or "auto"
        allow_retry = bool(request.allow_retry)
        if requested_reviewer_decision not in {"auto", "approved", "rework_required", "rejected"}:
            raise HTTPException(status_code=400, detail="reviewer_decision must be auto, approved, rework_required, or rejected")

        conn = get_conn()
        cur = conn.cursor()
        actor = require_actor_permission(cur, x_actor_name, "operate")
        ensure_agent_tables(cur)

        cur.execute(
            """
            SELECT id, user_input, status, result, error_message, runtime_overrides, created_at, updated_at
            FROM task_runs
            WHERE id = %s;
            """,
            (task_id,),
        )
        task_row = cur.fetchone()
        if not task_row:
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail="Task not found")

        cur.execute(
            """
            SELECT id, task_run_id, parent_agent_run_id, role, status, attempt, brief_artifact_id,
                   output_artifact_id, review_artifact_id, execution_mode, execution_request_json,
                   source_task_run_id, assigned_step_orders_json, assigned_model, assigned_tool_profile,
                   error_summary, cost_tokens_in, cost_tokens_out, cost_usd_estimate,
                   created_at, updated_at, started_at, completed_at
            FROM agent_runs
            WHERE task_run_id = %s
            ORDER BY id ASC;
            """,
            (task_id,),
        )
        agent_rows = cur.fetchall()
        if not agent_rows:
            cur.close()
            conn.close()
            raise HTTPException(status_code=409, detail="Task has no agent runs; bootstrap-demo first")

        manager_row = next((row for row in agent_rows if row["role"] == "manager"), None)
        specialist_rows = [row for row in agent_rows if row["role"] == "specialist"]
        reviewer_row = next((row for row in agent_rows if row["role"] == "reviewer"), None)
        if not manager_row or not specialist_rows:
            cur.close()
            conn.close()
            raise HTTPException(status_code=409, detail="Task is missing manager or specialist agent runs")

        cur.execute(
            """
            SELECT step_order, step_name, status, tool_name, input_payload, output_payload, error_message
            FROM task_steps
            WHERE task_id = %s
            ORDER BY step_order ASC;
            """,
            (task_id,),
        )
        step_rows = cur.fetchall()

        cur.execute(
            """
            SELECT id, agent_run_id, artifact_type, summary, content_json, version, created_at
            FROM agent_artifacts
            WHERE task_run_id = %s
            ORDER BY id ASC;
            """,
            (task_id,),
        )
        artifact_rows = [serialize_agent_artifact_row(row) for row in cur.fetchall()]
        artifact_by_id = {int(item["id"]): item for item in artifact_rows}
        final_artifacts = [item for item in artifact_rows if item["artifact_type"] == "final"]
        review_artifacts = [item for item in artifact_rows if item["artifact_type"] == "review"]
        existing_final = final_artifacts[-1] if final_artifacts else None
        if existing_final and not allow_retry:
            cur.close()
            conn.close()
            raise HTTPException(status_code=409, detail="Task already has a final artifact; finalize-demo is single-use per task")
        if existing_final and allow_retry and str(manager_row.get("status") or "") != "blocked":
            cur.close()
            conn.close()
            raise HTTPException(status_code=409, detail="allow_retry 仅支持 blocked manager 的返工重汇总")

        plan_artifact = next((item for item in artifact_rows if item["artifact_type"] == "plan"), None)
        next_final_version = max((int(item.get("version") or 1) for item in final_artifacts), default=0) + 1
        next_review_version = max((int(item.get("version") or 1) for item in review_artifacts), default=0) + 1
        created_artifact_ids: list[int] = []
        created_message_ids: list[int] = []
        specialist_draft_ids: list[int] = []

        manager_objective = summary or build_task_display_user_input(
            str(task_row.get("user_input") or ""),
            parse_maybe_json(task_row.get("runtime_overrides")) or {},
        )
        step_outline, specialist_step_partitions, step_status_counts = build_specialist_step_partitions(
            step_rows=step_rows,
            specialist_count=len(specialist_rows),
            task_row=task_row,
        )

        for index, specialist_row in enumerate(specialist_rows, start=1):
            existing_output_artifact_id = specialist_row.get("output_artifact_id")
            if existing_output_artifact_id:
                specialist_draft_ids.append(int(existing_output_artifact_id))
                continue
            draft_summary = f"specialist-{index} draft"
            assigned_steps = specialist_step_partitions[index - 1]
            execution_request = build_specialist_execution_request(
                slot=index,
                manager_objective=manager_objective,
                assigned_steps=assigned_steps,
                brief_artifact_id=specialist_row.get("brief_artifact_id"),
                plan_artifact_id=plan_artifact["id"] if plan_artifact else None,
                note=note,
            )
            existing_output_artifact = artifact_by_id.get(int(existing_output_artifact_id)) if existing_output_artifact_id else None
            draft_version = int((existing_output_artifact or {}).get("version") or 0) + 1
            created_message_ids.append(
                create_agent_message(
                    cur,
                    task_id,
                    specialist_row["id"],
                    "manager",
                    "specialist",
                    "handoff",
                    {
                        "protocol_version": multi_agent_protocol_version,
                        "task_run_id": task_id,
                        "subtask_type": "readonly_step_digest",
                        "execution_mode": "api_readonly_subtask_v1",
                        "assigned_step_orders": [int(step.get("step_order") or 0) for step in assigned_steps if int(step.get("step_order") or 0) > 0],
                        "manager_objective": manager_objective,
                        "note": note,
                        "force_rerun": False,
                        "execution_request": execution_request,
                    },
                )
            )
            draft_payload = build_specialist_draft_payload(
                slot=index,
                task_id=task_id,
                agent_run_id=int(specialist_row["id"]),
                manager_objective=manager_objective,
                task_row=task_row,
                step_outline=step_outline,
                assigned_steps=assigned_steps,
                plan_artifact_id=plan_artifact["id"] if plan_artifact else None,
                note=note,
                step_status_counts=step_status_counts,
                execution_request=execution_request,
            )
            draft_artifact_id = create_agent_artifact(
                cur,
                task_id,
                specialist_row["id"],
                "draft",
                draft_summary,
                draft_payload,
                version=draft_version,
            )
            specialist_draft_ids.append(draft_artifact_id)
            created_artifact_ids.append(draft_artifact_id)
            cur.execute(
                """
                UPDATE agent_runs
                SET status = 'completed',
                    attempt = attempt + 1,
                    output_artifact_id = %s,
                    execution_mode = %s,
                    execution_request_json = %s,
                    source_task_run_id = %s,
                    assigned_step_orders_json = %s,
                    error_summary = '',
                    started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                    completed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
                """,
                (
                    draft_artifact_id,
                    "api_readonly_subtask_v1",
                    safe_json_dumps(execution_request),
                    task_id,
                    safe_json_dumps(execution_request.get("assigned_step_orders") or []),
                    specialist_row["id"],
                ),
            )
            created_message_ids.append(
                create_agent_message(
                    cur,
                    task_id,
                    specialist_row["id"],
                    "specialist",
                    "manager",
                    "result",
                    {
                        "protocol_version": multi_agent_protocol_version,
                        "status": "completed",
                        "artifact_ids": [draft_artifact_id],
                        "summary": draft_summary,
                        "needs_human_review": False,
                    },
                )
            )

        review_artifact_id = None
        evaluator_run_id = None
        review_status = "not_requested"
        manager_status = "completed"
        manager_error_summary = ""
        next_strategy = "complete"
        reviewer_decision, decision_source = resolve_reviewer_decision(
            requested_decision=requested_reviewer_decision,
            task_status=str(task_row["status"]),
            step_rows=step_rows,
            specialist_draft_count=len(specialist_rows),
        )
        quality_bundle = build_demo_review_criteria(
            task_status=str(task_row["status"]),
            step_rows=step_rows,
            specialist_draft_count=len(specialist_rows),
            reviewer_decision=reviewer_decision,
        )
        failure_profile = derive_evaluator_failure_profile(
            task_status=str(task_row["status"]),
            step_rows=step_rows,
            specialist_draft_count=len(specialist_rows),
            reviewer_decision=reviewer_decision,
        )
        if reviewer_row:
            review_status = reviewer_decision
            blocking_issues = []
            follow_up_actions = []
            reasoning_summary = "bootstrap finalize demo 自动汇总后通过 reviewer 占位校验"
            if reviewer_decision == "rework_required":
                blocking_issues = ["reviewer 要求 manager 根据 specialist drafts 再做一轮返工"]
                follow_up_actions = ["补充 specialist draft 细节", "重新汇总 final candidate"]
                reasoning_summary = "reviewer 认为当前 drafts 已形成基础结果，但还需要返工后再提交"
                manager_status = "blocked"
                manager_error_summary = "reviewer requested rework"
                next_strategy = "retry_specialists"
            elif reviewer_decision == "rejected":
                blocking_issues = ["reviewer 拒绝当前 manager final candidate"]
                follow_up_actions = ["回退到 specialist 重新拆解", "必要时升级人工审批"]
                reasoning_summary = "reviewer 拒绝当前汇总结果，需要停止并重新规划"
                manager_status = "failed"
                manager_error_summary = "reviewer rejected final candidate"
                next_strategy = "escalate_to_operator"
            review_payload = {
                "protocol_version": multi_agent_protocol_version,
                "decision": reviewer_decision,
                "reasoning_summary": reasoning_summary,
                "blocking_issues": blocking_issues,
                "follow_up_actions": follow_up_actions,
                "source_artifact_refs": specialist_draft_ids,
                "quality_criteria": quality_bundle["criteria"],
                "quality_score": quality_bundle["score"],
                "step_stats": quality_bundle["step_stats"],
                "failure_reason": failure_profile["failure_reason"],
                "failure_stage": failure_profile["failure_stage"],
                "decision_source": decision_source,
                "requested_decision": requested_reviewer_decision,
                "note": note,
            }
            review_artifact_id = create_agent_artifact(
                cur,
                task_id,
                reviewer_row["id"],
                "review",
                "reviewer decision",
                review_payload,
                version=next_review_version,
            )
            created_artifact_ids.append(review_artifact_id)
            cur.execute(
                """
                UPDATE agent_runs
                SET status = 'completed',
                    review_artifact_id = %s,
                    started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                    completed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
                """,
                (review_artifact_id, reviewer_row["id"]),
            )
            created_message_ids.append(
                create_agent_message(
                    cur,
                    task_id,
                    reviewer_row["id"],
                    "reviewer",
                    "manager",
                    "review_decision",
                    {
                        "protocol_version": multi_agent_protocol_version,
                        "decision": reviewer_decision,
                        "reasoning_summary": reasoning_summary,
                        "blocking_issues": blocking_issues,
                        "follow_up_actions": follow_up_actions,
                        "quality_score": quality_bundle["score"],
                        "quality_criteria": quality_bundle["criteria"],
                        "failure_reason": failure_profile["failure_reason"],
                        "failure_stage": failure_profile["failure_stage"],
                        "decision_source": decision_source,
                        "requested_decision": requested_reviewer_decision,
                    },
                )
            )
            if reviewer_decision == "rework_required":
                for specialist_row in specialist_rows:
                    created_message_ids.append(
                        create_agent_message(
                            cur,
                            task_id,
                            specialist_row["id"],
                            "manager",
                            "specialist",
                            "handoff",
                            {
                                "protocol_version": multi_agent_protocol_version,
                                "task_run_id": task_id,
                                "reviewer_decision": reviewer_decision,
                                "follow_up_actions": follow_up_actions,
                                "manager_next_strategy": next_strategy,
                            },
                        )
                    )

        final_artifact_payload = {
            "protocol_version": multi_agent_protocol_version,
            "summary": summary or "manager 汇总了 specialist drafts 并生成 final artifact",
            "final_output": {
                "task_id": task_id,
                "objective": manager_objective,
                "specialist_draft_count": len(specialist_draft_ids),
                "review_status": review_status,
                "note": note,
                "task_status": task_row["status"],
                "step_count": len(step_rows),
                "next_strategy": next_strategy,
                "quality_score": quality_bundle["score"],
                "failure_reason": failure_profile["failure_reason"],
                "failure_stage": failure_profile["failure_stage"],
                "decision_source": decision_source,
            },
            "source_artifact_refs": specialist_draft_ids,
            "review_status": review_status,
            "next_strategy": next_strategy,
            "quality_criteria": quality_bundle["criteria"],
            "quality_score": quality_bundle["score"],
            "step_stats": quality_bundle["step_stats"],
            "failure_reason": failure_profile["failure_reason"],
            "failure_stage": failure_profile["failure_stage"],
            "decision_source": decision_source,
            "requested_decision": requested_reviewer_decision,
        }
        final_artifact_id = create_agent_artifact(
            cur,
            task_id,
            manager_row["id"],
            "final",
            "manager final artifact",
            final_artifact_payload,
            version=next_final_version,
        )
        created_artifact_ids.append(final_artifact_id)
        cur.execute(
            """
            UPDATE agent_runs
            SET status = %s,
                output_artifact_id = %s,
                error_summary = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
            """,
            (manager_status, final_artifact_id, manager_error_summary, manager_row["id"]),
        )
        created_message_ids.append(
            create_agent_message(
                cur,
                task_id,
                manager_row["id"],
                "manager",
                "operator",
                "result",
                {
                    "protocol_version": multi_agent_protocol_version,
                    "status": manager_status,
                    "artifact_ids": [final_artifact_id],
                    "summary": final_artifact_payload["summary"],
                    "needs_human_review": reviewer_decision != "approved",
                    "next_strategy": next_strategy,
                    "quality_score": quality_bundle["score"],
                    "failure_reason": failure_profile["failure_reason"],
                    "failure_stage": failure_profile["failure_stage"],
                    "final_artifact_version": next_final_version,
                    "decision_source": decision_source,
                },
            )
        )
        if reviewer_decision == "rejected":
            created_message_ids.append(
                create_agent_message(
                    cur,
                    task_id,
                    manager_row["id"],
                    "manager",
                    "operator",
                    "escalation",
                    {
                        "protocol_version": multi_agent_protocol_version,
                        "task_run_id": task_id,
                        "reviewer_decision": reviewer_decision,
                        "review_artifact_id": review_artifact_id,
                        "final_artifact_id": final_artifact_id,
                        "next_strategy": next_strategy,
                    },
                )
            )

        evaluator_summary = f"{failure_profile['summary']} score={quality_bundle['score']} decision={reviewer_decision}"
        evaluator_recommendation = failure_profile["recommendation"]
        workflow_proposal = build_workflow_proposal(
            task_id=task_id,
            reviewer_decision=reviewer_decision,
            failure_profile=failure_profile,
            quality_bundle=quality_bundle,
            next_strategy=next_strategy,
        )
        evaluator_run_id = create_evaluator_run(
            cur,
            task_run_id=task_id,
            manager_agent_run_id=int(manager_row["id"]),
            reviewer_agent_run_id=int(reviewer_row["id"]) if reviewer_row else None,
            final_artifact_id=final_artifact_id,
            review_artifact_id=review_artifact_id,
            decision=reviewer_decision,
            score=int(quality_bundle["score"]),
            failure_reason=failure_profile["failure_reason"],
            failure_stage=failure_profile["failure_stage"],
            criteria=quality_bundle["criteria"],
            step_stats=quality_bundle["step_stats"],
            workflow_proposal=workflow_proposal,
            summary=evaluator_summary,
            recommendation=evaluator_recommendation,
        )
        serialized_workflow_proposal = serialize_workflow_proposal(
            evaluator_run={
                "id": evaluator_run_id,
                "task_run_id": task_id,
                "decision": reviewer_decision,
                "score": int(quality_bundle["score"]),
                "failure_reason": failure_profile["failure_reason"],
                "failure_stage": failure_profile["failure_stage"],
                "source": "stage5_finalize_demo",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "workflow_proposal": workflow_proposal,
            },
            proposal=workflow_proposal,
        )
        insert_audit_log(
            cur,
            "evaluator.recorded",
            actor["actor_name"],
            task_id,
            {
                "task_id": task_id,
                "evaluator_run_id": evaluator_run_id,
                "manager_run_id": manager_row["id"],
                "reviewer_run_id": reviewer_row["id"] if reviewer_row else None,
                "decision": reviewer_decision,
                "score": quality_bundle["score"],
                "failure_reason": failure_profile["failure_reason"],
                "failure_stage": failure_profile["failure_stage"],
                "source": "stage5_finalize_demo",
                "workflow_proposal": serialized_workflow_proposal,
            },
        )

        insert_audit_log(
            cur,
            "agent.finalize_demo",
            actor["actor_name"],
            task_id,
            {
                "task_id": task_id,
                "manager_run_id": manager_row["id"],
                "specialist_count": len(specialist_rows),
                "reviewer_run_id": reviewer_row["id"] if reviewer_row else None,
                "final_artifact_id": final_artifact_id,
                "reviewer_decision": reviewer_decision,
                "decision_source": decision_source,
                "requested_decision": requested_reviewer_decision,
                "next_strategy": next_strategy,
                "quality_score": quality_bundle["score"],
                "allow_retry": allow_retry,
                "final_artifact_version": next_final_version,
            },
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.info(
            "agent finalize demo completed task_id=%s manager_run_id=%s specialists=%s reviewer=%s actor=%s",
            task_id,
            manager_row["id"],
            len(specialist_rows),
            reviewer_row["id"] if reviewer_row else None,
            actor["actor_name"],
        )
        return {
            "message": "agent finalize demo completed",
            "task_id": task_id,
            "manager_run_id": manager_row["id"],
            "final_artifact_id": final_artifact_id,
            "review_artifact_id": review_artifact_id,
            "specialist_draft_artifact_ids": specialist_draft_ids,
            "reviewer_decision": reviewer_decision,
            "decision_source": decision_source,
            "requested_decision": requested_reviewer_decision,
            "manager_status": manager_status,
            "next_strategy": next_strategy,
            "quality_score": quality_bundle["score"],
            "quality_criteria": quality_bundle["criteria"],
            "failure_reason": failure_profile["failure_reason"],
            "failure_stage": failure_profile["failure_stage"],
            "workflow_proposal": serialized_workflow_proposal,
            "created_message_count": len(created_message_ids),
            "created_artifact_count": len(created_artifact_ids),
            "allow_retry": allow_retry,
            "final_artifact_version": next_final_version,
            "evaluator_run_id": evaluator_run_id,
        }

    return router
