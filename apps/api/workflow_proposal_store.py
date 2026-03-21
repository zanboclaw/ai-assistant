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
