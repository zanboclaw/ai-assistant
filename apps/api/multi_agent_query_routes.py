from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Header, HTTPException


def load_workflow_proposal_or_404(
    cur,
    *,
    proposal_id: int,
    get_workflow_proposal_or_404: Callable[..., dict[str, Any]],
    serialize_evaluator_run_row: Callable[[dict[str, Any]], dict[str, Any]],
    serialize_workflow_proposal: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    return get_workflow_proposal_or_404(
        cur,
        proposal_id,
        serialize_evaluator_run_row_fn=serialize_evaluator_run_row,
        serialize_workflow_proposal_fn=serialize_workflow_proposal,
    )


def register_multi_agent_query_routes(
    *,
    get_conn: Callable[[], Any],
    require_actor_permission: Callable[[Any, str | None, str], dict[str, Any]],
    serialize_agent_run_row: Callable[[dict[str, Any]], dict[str, Any]],
    serialize_agent_message_row: Callable[[dict[str, Any]], dict[str, Any]],
    serialize_agent_artifact_row: Callable[[dict[str, Any]], dict[str, Any]],
    fetch_task_agent_summary: Callable[[Any, int], dict[str, Any]],
    serialize_evaluator_run_row: Callable[[dict[str, Any]], dict[str, Any]],
    serialize_workflow_proposal: Callable[..., dict[str, Any]],
    fetch_latest_evaluator_for_task: Callable[[Any, int], dict[str, Any] | None],
    list_workflow_proposals_rows: Callable[..., list[dict[str, Any]]],
    task_exists: Callable[[Any, int], bool],
    get_workflow_proposal_or_404: Callable[..., dict[str, Any]],
    build_workflow_proposal_shadow_validation_response: Callable[..., dict[str, Any]],
    build_workflow_proposal_shadow_status: Callable[..., dict[str, Any]],
    build_workflow_proposal_shadow_validation_status_with_context: Callable[..., dict[str, Any]],
    get_workflow_proposal_change_request_draft_response: Callable[..., dict[str, Any]],
    suggest_change_request_draft_from_workflow_proposal_with_context: Callable[..., dict[str, Any]],
    attach_patch_artifacts_to_change_request_draft_with_context: Callable[..., dict[str, Any]],
    attach_shadow_validation_state_to_change_request_draft_with_context: Callable[..., dict[str, Any]],
    fetch_evaluator_run_row: Callable[[Any, int], dict[str, Any] | None],
    get_evaluator_run_or_404: Callable[..., dict[str, Any]],
):
    router = APIRouter()

    def fetch_evaluator_runs(
        cur,
        *,
        task_id: int | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if task_id is not None:
            clauses.append("task_run_id = %s")
            params.append(int(task_id))
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        row_limit = max(1, min(int(limit or 20), 200))
        cur.execute(
            f"""
            SELECT id, task_run_id, manager_agent_run_id, reviewer_agent_run_id, final_artifact_id, review_artifact_id,
                   evaluator_kind, status, decision, score, failure_reason, failure_stage,
                   criteria_json, step_stats_json, proposal_json, summary, recommendation,
                   source, created_at
            FROM evaluator_runs
            {where_sql}
            ORDER BY id DESC
            LIMIT %s;
            """,
            (*params, row_limit),
        )
        return [serialize_evaluator_run_row(row) for row in cur.fetchall()]

    @router.get("/agent-runs")
    def list_agent_runs(
        task_id: int | None = None,
        role: str | None = None,
        status: str | None = None,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        clauses: list[str] = []
        params: list[Any] = []
        if task_id is not None:
            clauses.append("task_run_id = %s")
            params.append(int(task_id))
        if role:
            clauses.append("role = %s")
            params.append(role.strip())
        if status:
            clauses.append("status = %s")
            params.append(status.strip())
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cur.execute(
            f"""
            SELECT id, task_run_id, parent_agent_run_id, role, status, attempt, brief_artifact_id,
                   output_artifact_id, review_artifact_id, execution_mode, execution_request_json,
                   source_task_run_id, assigned_step_orders_json, assigned_model, assigned_tool_profile,
                   error_summary, cost_tokens_in, cost_tokens_out, cost_usd_estimate,
                   created_at, updated_at, started_at, completed_at
            FROM agent_runs
            {where_sql}
            ORDER BY id DESC;
            """,
            tuple(params),
        )
        rows = [serialize_agent_run_row(row) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return rows

    @router.get("/tasks/{task_id}/agent-runs")
    def list_task_agent_runs(task_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        return list_agent_runs(task_id=task_id, x_actor_name=x_actor_name)

    @router.get("/tasks/{task_id}/agent-runs/summary")
    def get_task_agent_run_summary(task_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        cur.execute("SELECT id FROM task_runs WHERE id = %s;", (task_id,))
        task_row = cur.fetchone()
        if not task_row:
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail="Task not found")

        result = fetch_task_agent_summary(cur, task_id)
        cur.close()
        conn.close()
        return result

    @router.get("/agent-runs/{agent_run_id}")
    def get_agent_run(agent_run_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        cur.execute(
            """
            SELECT id, task_run_id, parent_agent_run_id, role, status, attempt, brief_artifact_id,
                   output_artifact_id, review_artifact_id, execution_mode, execution_request_json,
                   source_task_run_id, assigned_step_orders_json, assigned_model, assigned_tool_profile,
                   error_summary, cost_tokens_in, cost_tokens_out, cost_usd_estimate,
                   created_at, updated_at, started_at, completed_at
            FROM agent_runs
            WHERE id = %s;
            """,
            (agent_run_id,),
        )
        row = cur.fetchone()
        if not row:
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail="Agent run not found")
        result = serialize_agent_run_row(row)
        cur.close()
        conn.close()
        return result

    @router.get("/agent-runs/{agent_run_id}/messages")
    def list_agent_run_messages(
        agent_run_id: int,
        limit: int | None = 50,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        cur.execute("SELECT id FROM agent_runs WHERE id = %s;", (agent_run_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail="Agent run not found")
        row_limit = max(1, min(int(limit or 50), 200))
        cur.execute(
            """
            SELECT id, task_run_id, agent_run_id, sender_role, recipient_role, message_type, payload_json, created_at
            FROM agent_messages
            WHERE agent_run_id = %s
            ORDER BY id DESC
            LIMIT %s;
            """,
            (agent_run_id, row_limit),
        )
        rows = [serialize_agent_message_row(row) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return rows

    @router.get("/agent-runs/{agent_run_id}/artifacts")
    def list_agent_run_artifacts(
        agent_run_id: int,
        limit: int | None = 50,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        cur.execute(
            """
            SELECT id, brief_artifact_id, output_artifact_id, review_artifact_id
            FROM agent_runs
            WHERE id = %s;
            """,
            (agent_run_id,),
        )
        agent_run = cur.fetchone()
        if not agent_run:
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail="Agent run not found")
        row_limit = max(1, min(int(limit or 50), 200))
        referenced_artifact_ids = [
            artifact_id
            for artifact_id in [
                agent_run.get("brief_artifact_id"),
                agent_run.get("output_artifact_id"),
                agent_run.get("review_artifact_id"),
            ]
            if artifact_id is not None
        ]
        cur.execute(
            """
            SELECT id, task_run_id, agent_run_id, artifact_type, summary, content_json, version, created_at
            FROM agent_artifacts
            WHERE agent_run_id = %s
               OR id = ANY(%s)
            ORDER BY id DESC
            LIMIT %s;
            """,
            (agent_run_id, referenced_artifact_ids, row_limit),
        )
        rows = [serialize_agent_artifact_row(row) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return rows

    @router.get("/evaluator-runs")
    def list_evaluator_runs(
        task_id: int | None = None,
        limit: int = 20,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        try:
            require_actor_permission(cur, x_actor_name, "read")
            return fetch_evaluator_runs(cur, task_id=task_id, limit=limit)
        finally:
            cur.close()
            conn.close()

    @router.get("/tasks/{task_id}/evaluator-runs")
    def list_task_evaluator_runs(
        task_id: int,
        limit: int = 20,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        return list_evaluator_runs(task_id=task_id, limit=limit, x_actor_name=x_actor_name)

    @router.get("/tasks/{task_id}/evaluator-runs/latest")
    def get_latest_task_evaluator_run(task_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        try:
            require_actor_permission(cur, x_actor_name, "read")
            if not task_exists(cur, task_id):
                raise HTTPException(status_code=404, detail="Task not found")
            latest = fetch_latest_evaluator_for_task(cur, task_id)
            if not latest:
                raise HTTPException(status_code=404, detail="No evaluator runs found for this task")
            return latest
        finally:
            cur.close()
            conn.close()

    @router.get("/tasks/{task_id}/workflow-proposals/latest")
    def get_latest_task_workflow_proposal(
        task_id: int,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        try:
            require_actor_permission(cur, x_actor_name, "read")
            if not task_exists(cur, task_id):
                raise HTTPException(status_code=404, detail="Task not found")
            latest = fetch_latest_evaluator_for_task(cur, task_id)
            proposal = (latest or {}).get("workflow_proposal") or {}
            if not latest or not proposal:
                raise HTTPException(status_code=404, detail="No workflow proposal found for this task")
            return serialize_workflow_proposal(evaluator_run=latest, proposal=proposal)
        finally:
            cur.close()
            conn.close()

    @router.get("/workflow-proposals")
    def list_workflow_proposals(
        task_id: int | None = None,
        action_key: str | None = None,
        priority: str | None = None,
        limit: int = 20,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        try:
            require_actor_permission(cur, x_actor_name, "read")
            return list_workflow_proposals_rows(
                cur,
                task_id=task_id,
                action_key=action_key,
                priority=priority,
                limit=limit,
            )
        finally:
            cur.close()
            conn.close()

    @router.get("/tasks/{task_id}/workflow-proposals")
    def list_task_workflow_proposals(
        task_id: int,
        limit: int = 20,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        try:
            require_actor_permission(cur, x_actor_name, "read")
            if not task_exists(cur, task_id):
                raise HTTPException(status_code=404, detail="Task not found")
            return list_workflow_proposals_rows(cur, task_id=task_id, limit=limit)
        finally:
            cur.close()
            conn.close()

    @router.get("/workflow-proposals/{proposal_id}")
    def get_workflow_proposal(proposal_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        try:
            require_actor_permission(cur, x_actor_name, "read")
            return load_workflow_proposal_or_404(
                cur,
                proposal_id=proposal_id,
                get_workflow_proposal_or_404=get_workflow_proposal_or_404,
                serialize_evaluator_run_row=serialize_evaluator_run_row,
                serialize_workflow_proposal=serialize_workflow_proposal,
            )
        finally:
            cur.close()
            conn.close()

    @router.get("/workflow-proposals/{proposal_id}/shadow-validation")
    def get_workflow_proposal_shadow_validation(
        proposal_id: int,
        history_limit: int = 10,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        try:
            require_actor_permission(cur, x_actor_name, "read")
            workflow_proposal = load_workflow_proposal_or_404(
                cur,
                proposal_id=proposal_id,
                get_workflow_proposal_or_404=get_workflow_proposal_or_404,
                serialize_evaluator_run_row=serialize_evaluator_run_row,
                serialize_workflow_proposal=serialize_workflow_proposal,
            )
            return build_workflow_proposal_shadow_validation_response(
                cur,
                workflow_proposal=workflow_proposal,
                proposal_id=proposal_id,
                history_limit=history_limit,
                build_workflow_proposal_shadow_status_fn=lambda current_cur, **kwargs: build_workflow_proposal_shadow_status(
                    current_cur,
                    build_workflow_proposal_shadow_validation_status_fn=build_workflow_proposal_shadow_validation_status_with_context,
                    **kwargs,
                ),
            )
        finally:
            cur.close()
            conn.close()

    @router.get("/workflow-proposals/{proposal_id}/change-request-draft")
    def preview_workflow_proposal_change_request_draft(
        proposal_id: int,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        try:
            require_actor_permission(cur, x_actor_name, "read")
            workflow_proposal = load_workflow_proposal_or_404(
                cur,
                proposal_id=proposal_id,
                get_workflow_proposal_or_404=get_workflow_proposal_or_404,
                serialize_evaluator_run_row=serialize_evaluator_run_row,
                serialize_workflow_proposal=serialize_workflow_proposal,
            )
            return get_workflow_proposal_change_request_draft_response(
                cur,
                workflow_proposal=workflow_proposal,
                suggest_change_request_draft_from_workflow_proposal_fn=suggest_change_request_draft_from_workflow_proposal_with_context,
                attach_patch_artifacts_to_change_request_draft_fn=attach_patch_artifacts_to_change_request_draft_with_context,
                attach_shadow_validation_state_to_change_request_draft_fn=attach_shadow_validation_state_to_change_request_draft_with_context,
            )
        finally:
            cur.close()
            conn.close()

    @router.get("/evaluator-runs/{evaluator_run_id}")
    def get_evaluator_run(evaluator_run_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        try:
            require_actor_permission(cur, x_actor_name, "read")
            return get_evaluator_run_or_404(
                cur,
                evaluator_run_id,
                fetch_evaluator_run_row_fn=fetch_evaluator_run_row,
                serialize_evaluator_run_row_fn=serialize_evaluator_run_row,
            )
        finally:
            cur.close()
            conn.close()

    return router
