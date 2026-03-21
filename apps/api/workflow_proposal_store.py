from typing import Any

from fastapi import HTTPException


def fetch_evaluator_run_row(cur, evaluator_run_id: int) -> dict[str, Any] | None:
    cur.execute(
        """
        SELECT id, task_run_id, manager_agent_run_id, reviewer_agent_run_id, final_artifact_id, review_artifact_id,
               evaluator_kind, status, decision, score, failure_reason, failure_stage,
               criteria_json, step_stats_json, proposal_json, summary, recommendation,
               source, created_at
        FROM evaluator_runs
        WHERE id = %s;
        """,
        (evaluator_run_id,),
    )
    return cur.fetchone()


def task_exists(cur, task_id: int) -> bool:
    cur.execute("SELECT id FROM task_runs WHERE id = %s;", (task_id,))
    return bool(cur.fetchone())


def get_workflow_proposal_or_404(
    cur,
    proposal_id: int,
    *,
    serialize_evaluator_run_row_fn,
    serialize_workflow_proposal_fn,
) -> dict[str, Any]:
    row = fetch_evaluator_run_row(cur, proposal_id)
    if not row:
        raise HTTPException(status_code=404, detail="Workflow proposal not found")
    evaluator_run = serialize_evaluator_run_row_fn(row)
    proposal = (evaluator_run or {}).get("workflow_proposal") or {}
    if not proposal:
        raise HTTPException(status_code=404, detail="Workflow proposal not found")
    return serialize_workflow_proposal_fn(evaluator_run=evaluator_run, proposal=proposal)


def build_workflow_proposal_shadow_status(
    cur,
    *,
    workflow_proposal: dict[str, Any],
    proposal_id: int,
    history_limit: int,
    build_workflow_proposal_shadow_validation_status_fn,
) -> dict[str, Any]:
    supported = (
        str(workflow_proposal.get("source") or "") == "task_runtime_postrun_v1"
        and int(workflow_proposal.get("task_run_id") or 0) > 0
    )
    return build_workflow_proposal_shadow_validation_status_fn(
        cur,
        proposal_id,
        history_limit=history_limit,
        supported=supported,
    )


def ensure_workflow_proposal_shadow_validation_supported(workflow_proposal: dict[str, Any]) -> tuple[int, int]:
    if str(workflow_proposal.get("source") or "") != "task_runtime_postrun_v1":
        raise HTTPException(status_code=400, detail="Shadow validation currently only supports mainline workflow proposals")

    proposal_id = int(workflow_proposal.get("id") or 0)
    baseline_task_id = int(workflow_proposal.get("task_run_id") or 0)
    if baseline_task_id <= 0:
        raise HTTPException(status_code=400, detail="Workflow proposal is missing baseline task context")
    return proposal_id, baseline_task_id


def ensure_change_request_shadow_validation_eligible(change_request: dict[str, Any], *, parse_optional_int_fn) -> int:
    if not change_request.get("requires_shadow_validation"):
        raise HTTPException(status_code=400, detail="Change request does not require shadow validation")
    if change_request.get("status") not in {"pending", "approved"}:
        raise HTTPException(status_code=400, detail="Only pending or approved change requests can run shadow validation")

    proposal_id = parse_optional_int_fn(change_request.get("source_workflow_proposal_id"))
    if proposal_id is None or proposal_id <= 0:
        raise HTTPException(status_code=400, detail="Change request is missing workflow proposal context")
    return int(proposal_id)


def create_shadow_validation_task(
    cur,
    *,
    shadow_user_input: str,
    session_id: int | None,
    actor_name: str,
    runtime_overrides: dict[str, Any] | None,
    safe_json_dumps_fn,
    insert_audit_log_fn,
    task_create_details: dict[str, Any],
    validation_request: dict[str, Any],
    baseline_task_id: int,
) -> dict[str, Any]:
    cur.execute(
        """
        INSERT INTO task_runs (user_input, session_id, created_by_actor, status, runtime_overrides)
        VALUES (%s, %s, %s, 'pending', %s)
        RETURNING id, session_id, user_input, created_by_actor, status, runtime_overrides, created_at;
        """,
        (
            shadow_user_input,
            session_id,
            actor_name,
            safe_json_dumps_fn(runtime_overrides) if runtime_overrides else None,
        ),
    )
    shadow_task = cur.fetchone()
    validation_request["shadow_task_id"] = int(shadow_task["id"])
    insert_audit_log_fn(
        cur,
        "task.create",
        actor_name,
        int(shadow_task["id"]),
        task_create_details,
    )
    insert_audit_log_fn(
        cur,
        "workflow_proposal.shadow_validation",
        actor_name,
        baseline_task_id,
        validation_request,
    )
    return shadow_task


def prepare_workflow_proposal_shadow_validation_context(
    cur,
    *,
    workflow_proposal: dict[str, Any],
    request,
    x_actor_name: str | None,
    source_change_request: dict[str, Any] | None,
    require_actor_permission_fn,
    enforce_task_quota_fn,
    prepare_shadow_validation_baseline_fn,
    resolve_shadow_validation_candidate_overlay_fn,
    build_shadow_validation_runtime_overrides_fn,
    build_shadow_validation_execution_payload_fn,
    parse_optional_int_fn,
) -> dict[str, Any]:
    proposal_id, baseline_task_id = ensure_workflow_proposal_shadow_validation_supported(workflow_proposal)
    actor = require_actor_permission_fn(cur, x_actor_name, "operate")
    quota_snapshot = enforce_task_quota_fn(cur, actor["actor_name"])
    cur.execute(
        """
        SELECT id, session_id, user_input, created_by_actor, status, runtime_overrides, created_at
        FROM task_runs
        WHERE id = %s;
        """,
        (baseline_task_id,),
    )
    baseline_prepared = prepare_shadow_validation_baseline_fn(
        baseline_task=cur.fetchone(),
        request=request,
    )
    baseline_task = baseline_prepared["baseline_task"]
    shadow_user_input = baseline_prepared["shadow_user_input"]

    candidate_overlay = resolve_shadow_validation_candidate_overlay_fn(
        cur,
        workflow_proposal=workflow_proposal,
        request=request,
        source_change_request=source_change_request,
    )
    validation_mode = "candidate_overlay_compare" if candidate_overlay else "task_replay_compare"
    runtime_overrides = build_shadow_validation_runtime_overrides_fn(
        proposal_id=proposal_id,
        validation_mode=validation_mode,
        candidate_overlay=candidate_overlay,
        source_change_request_id=parse_optional_int_fn((source_change_request or {}).get("id")),
    )
    execution_payload = build_shadow_validation_execution_payload_fn(
        workflow_proposal=workflow_proposal,
        baseline_task=baseline_task,
        request=request,
        actor=actor,
        quota_snapshot=quota_snapshot,
        candidate_overlay=candidate_overlay,
        runtime_overrides=runtime_overrides,
        shadow_task={
            "id": 0,
            "session_id": baseline_task.get("session_id"),
            "user_input": shadow_user_input,
        },
    )
    return {
        "proposal_id": proposal_id,
        "baseline_task_id": baseline_task_id,
        "actor": actor,
        "quota_snapshot": quota_snapshot,
        "baseline_task": baseline_task,
        "shadow_user_input": shadow_user_input,
        "candidate_overlay": candidate_overlay,
        "validation_mode": validation_mode,
        "runtime_overrides": runtime_overrides,
        "execution_payload": execution_payload,
    }


def launch_workflow_proposal_shadow_validation(
    cur,
    *,
    workflow_proposal: dict[str, Any],
    request,
    x_actor_name: str | None,
    source_change_request: dict[str, Any] | None,
    require_actor_permission_fn,
    enforce_task_quota_fn,
    prepare_shadow_validation_baseline_fn,
    resolve_shadow_validation_candidate_overlay_fn,
    build_shadow_validation_runtime_overrides_fn,
    build_shadow_validation_execution_payload_fn,
    parse_optional_int_fn,
    safe_json_dumps_fn,
    insert_audit_log_fn,
) -> dict[str, Any]:
    shadow_context = prepare_workflow_proposal_shadow_validation_context(
        cur,
        workflow_proposal=workflow_proposal,
        request=request,
        x_actor_name=x_actor_name,
        source_change_request=source_change_request,
        require_actor_permission_fn=require_actor_permission_fn,
        enforce_task_quota_fn=enforce_task_quota_fn,
        prepare_shadow_validation_baseline_fn=prepare_shadow_validation_baseline_fn,
        resolve_shadow_validation_candidate_overlay_fn=resolve_shadow_validation_candidate_overlay_fn,
        build_shadow_validation_runtime_overrides_fn=build_shadow_validation_runtime_overrides_fn,
        build_shadow_validation_execution_payload_fn=build_shadow_validation_execution_payload_fn,
        parse_optional_int_fn=parse_optional_int_fn,
    )
    shadow_task = create_shadow_validation_task(
        cur,
        shadow_user_input=shadow_context["shadow_user_input"],
        session_id=shadow_context["baseline_task"].get("session_id"),
        actor_name=shadow_context["actor"]["actor_name"],
        runtime_overrides=shadow_context["runtime_overrides"],
        safe_json_dumps_fn=safe_json_dumps_fn,
        insert_audit_log_fn=insert_audit_log_fn,
        task_create_details=shadow_context["execution_payload"]["task_create_details"],
        validation_request=shadow_context["execution_payload"]["validation_request"],
        baseline_task_id=shadow_context["baseline_task_id"],
    )
    return {
        "shadow_context": shadow_context,
        "shadow_task": shadow_task,
    }


def complete_workflow_proposal_shadow_validation(
    *,
    workflow_proposal: dict[str, Any],
    request,
    source_change_request: dict[str, Any] | None,
    shadow_context: dict[str, Any],
    shadow_task: dict[str, Any],
    enqueue_task_fn,
    finalize_shadow_validation_response_fn,
) -> dict[str, Any]:
    enqueue_task_fn(int(shadow_task["id"]))
    timeout_seconds = max(5, min(int(request.timeout_seconds or 45), 180))
    poll_interval_seconds = max(0.5, min(float(request.poll_interval_seconds or 1.0), 5.0))
    return finalize_shadow_validation_response_fn(
        workflow_proposal=workflow_proposal,
        baseline_task=shadow_context["baseline_task"],
        shadow_task=shadow_task,
        validation_request=shadow_context["execution_payload"]["validation_request"],
        candidate_overlay=shadow_context["candidate_overlay"],
        validation_mode=shadow_context["validation_mode"],
        source_change_request=source_change_request,
        await_completion=bool(request.await_completion),
        actor_name=shadow_context["actor"]["actor_name"],
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        runtime_overrides=shadow_context["runtime_overrides"],
    )


def build_workflow_proposal_change_request_draft(
    cur,
    *,
    workflow_proposal: dict[str, Any],
    suggest_change_request_draft_from_workflow_proposal_fn,
    attach_patch_artifacts_to_change_request_draft_fn,
    attach_shadow_validation_state_to_change_request_draft_fn,
) -> dict[str, Any]:
    draft = suggest_change_request_draft_from_workflow_proposal_fn(cur, workflow_proposal)
    draft = attach_patch_artifacts_to_change_request_draft_fn(cur, draft)
    draft = attach_shadow_validation_state_to_change_request_draft_fn(cur, draft)
    return draft


def get_workflow_proposal_change_request_draft_response(
    cur,
    *,
    workflow_proposal: dict[str, Any],
    suggest_change_request_draft_from_workflow_proposal_fn,
    attach_patch_artifacts_to_change_request_draft_fn,
    attach_shadow_validation_state_to_change_request_draft_fn,
) -> dict[str, Any]:
    return build_workflow_proposal_change_request_draft(
        cur,
        workflow_proposal=workflow_proposal,
        suggest_change_request_draft_from_workflow_proposal_fn=suggest_change_request_draft_from_workflow_proposal_fn,
        attach_patch_artifacts_to_change_request_draft_fn=attach_patch_artifacts_to_change_request_draft_fn,
        attach_shadow_validation_state_to_change_request_draft_fn=attach_shadow_validation_state_to_change_request_draft_fn,
    )


def resolve_change_request_shadow_validation_target(
    cur,
    *,
    change_request_id: int,
    x_actor_name: str | None,
    require_actor_permission_fn,
    get_change_request_or_404_fn,
    ensure_change_requests_table_fn,
    ensure_change_request_shadow_validation_eligible_fn,
    parse_optional_int_fn,
    get_workflow_proposal_fn,
) -> dict[str, Any]:
    require_actor_permission_fn(cur, x_actor_name, "operate")
    change_request = get_change_request_or_404_fn(cur, ensure_change_requests_table_fn, change_request_id)
    proposal_id = ensure_change_request_shadow_validation_eligible_fn(
        change_request,
        parse_optional_int_fn=parse_optional_int_fn,
    )
    workflow_proposal = get_workflow_proposal_fn(proposal_id)
    return {
        "change_request": change_request,
        "proposal_id": proposal_id,
        "workflow_proposal": workflow_proposal,
    }


def create_change_request_from_workflow_proposal_draft(
    cur,
    *,
    proposal_id: int,
    workflow_proposal: dict[str, Any],
    request,
    x_actor_name: str | None,
    supported_change_target_types: set[str],
    require_actor_permission_fn,
    build_change_request_draft_from_workflow_proposal_fn,
    create_change_request_row_fn,
    serialize_change_request_row_fn,
    record_audit_event_fn,
) -> dict[str, Any]:
    draft = build_change_request_draft_from_workflow_proposal_fn(
        workflow_proposal=workflow_proposal,
        target_type=request.target_type,
        target_key=request.target_key,
        proposed_payload=request.proposed_payload,
        rationale=request.rationale,
    )
    target_type = str(draft.get("target_type") or "")
    target_key = str(draft.get("target_key") or "")
    proposed_payload = draft.get("proposed_payload") or {}
    if target_type not in supported_change_target_types:
        raise HTTPException(status_code=400, detail=f"Unsupported change target type: {target_type}")
    if not target_key:
        raise HTTPException(status_code=400, detail="target_key is required")

    actor = require_actor_permission_fn(cur, x_actor_name, "operate")
    row = create_change_request_row_fn(
        cur,
        target_type=target_type,
        target_key=target_key,
        proposed_payload=proposed_payload,
        rationale=str(draft.get("rationale") or ""),
        requested_by_actor=actor["actor_name"],
        proposal_kind="workflow_improvement",
        source_workflow_proposal_id=proposal_id,
    )
    serialized_row = serialize_change_request_row_fn(row)
    record_audit_event_fn(
        "workflow_proposal.change_request_create",
        actor["actor_name"],
        int(workflow_proposal.get("task_run_id") or 0) or None,
        {
            "proposal_id": proposal_id,
            "change_request_id": serialized_row["id"],
            "target_type": target_type,
            "target_key": target_key,
            "proposal_kind": "workflow_improvement",
            "patch_summary": serialized_row["patch_summary"],
        },
    )
    return {
        "change_request": serialized_row,
        "workflow_proposal": workflow_proposal,
    }


def get_evaluator_run_or_404(
    cur,
    evaluator_run_id: int,
    *,
    fetch_evaluator_run_row_fn,
    serialize_evaluator_run_row_fn,
) -> dict[str, Any]:
    row = fetch_evaluator_run_row_fn(cur, evaluator_run_id)
    if not row:
        raise HTTPException(status_code=404, detail="Evaluator run not found")
    return serialize_evaluator_run_row_fn(row)


def list_evaluator_runs_response(
    cur,
    *,
    task_id: int | None = None,
    limit: int = 20,
    serialize_evaluator_run_row_fn,
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
    return [serialize_evaluator_run_row_fn(row) for row in cur.fetchall()]


def get_latest_task_evaluator_run_response(
    cur,
    *,
    task_id: int,
    task_exists_fn,
    fetch_latest_evaluator_for_task_fn,
) -> dict[str, Any]:
    if not task_exists_fn(cur, task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    latest = fetch_latest_evaluator_for_task_fn(cur, task_id)
    if not latest:
        raise HTTPException(status_code=404, detail="No evaluator runs found for this task")
    return latest


def get_latest_task_workflow_proposal_response(
    cur,
    *,
    task_id: int,
    task_exists_fn,
    fetch_latest_evaluator_for_task_fn,
    serialize_workflow_proposal_fn,
) -> dict[str, Any]:
    latest = get_latest_task_evaluator_run_response(
        cur,
        task_id=task_id,
        task_exists_fn=task_exists_fn,
        fetch_latest_evaluator_for_task_fn=fetch_latest_evaluator_for_task_fn,
    )
    proposal = (latest or {}).get("workflow_proposal") or {}
    if not proposal:
        raise HTTPException(status_code=404, detail="No workflow proposal found for this task")
    return serialize_workflow_proposal_fn(evaluator_run=latest, proposal=proposal)


def list_workflow_proposals_response(
    cur,
    *,
    task_id: int | None = None,
    action_key: str | None = None,
    priority: str | None = None,
    limit: int = 20,
    list_workflow_proposals_rows_fn,
) -> list[dict[str, Any]]:
    return list_workflow_proposals_rows_fn(
        cur,
        task_id=task_id,
        action_key=action_key,
        priority=priority,
        limit=limit,
    )


def list_task_workflow_proposals_or_404(
    cur,
    *,
    task_id: int,
    limit: int = 20,
    task_exists_fn,
    list_workflow_proposals_rows_fn,
) -> list[dict[str, Any]]:
    if not task_exists_fn(cur, task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return list_workflow_proposals_rows_fn(cur, task_id=task_id, limit=limit)


def get_workflow_proposal_response(
    cur,
    *,
    proposal_id: int,
    get_workflow_proposal_or_404_fn,
    serialize_evaluator_run_row_fn,
    serialize_workflow_proposal_fn,
) -> dict[str, Any]:
    return get_workflow_proposal_or_404_fn(
        cur,
        proposal_id,
        serialize_evaluator_run_row_fn=serialize_evaluator_run_row_fn,
        serialize_workflow_proposal_fn=serialize_workflow_proposal_fn,
    )


def build_workflow_proposal_shadow_validation_response(
    cur,
    *,
    workflow_proposal: dict[str, Any],
    proposal_id: int,
    history_limit: int,
    build_workflow_proposal_shadow_status_fn,
) -> dict[str, Any]:
    status = build_workflow_proposal_shadow_status_fn(
        cur,
        workflow_proposal=workflow_proposal,
        proposal_id=proposal_id,
        history_limit=history_limit,
    )
    return {
        "workflow_proposal": workflow_proposal,
        **status,
    }
