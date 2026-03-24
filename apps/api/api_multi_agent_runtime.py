from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable


def create_agent_artifact(
    cur,
    task_run_id: int,
    agent_run_id: int | None,
    artifact_type: str,
    summary: str,
    content: Any,
    version: int = 1,
    *,
    safe_json_dumps: Callable[[Any], str],
) -> int:
    cur.execute(
        """
        INSERT INTO agent_artifacts (task_run_id, agent_run_id, artifact_type, summary, content_json, version)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id;
        """,
        (task_run_id, agent_run_id, artifact_type, summary, safe_json_dumps(content), int(version)),
    )
    return int(cur.fetchone()["id"])


def create_evaluator_run(
    cur,
    *,
    task_run_id: int,
    manager_agent_run_id: int | None,
    reviewer_agent_run_id: int | None,
    final_artifact_id: int | None,
    review_artifact_id: int | None,
    decision: str,
    score: int,
    failure_reason: str,
    failure_stage: str,
    criteria: Any,
    step_stats: Any,
    workflow_proposal: Any,
    summary: str,
    recommendation: str,
    ensure_evaluator_tables: Callable[[Any], None],
    safe_json_dumps: Callable[[Any], str],
    source: str = "stage5_finalize_demo",
    evaluator_kind: str = "stage6_quality_gate",
    status: str = "completed",
) -> int:
    ensure_evaluator_tables(cur)
    cur.execute(
        """
        INSERT INTO evaluator_runs (
            task_run_id, manager_agent_run_id, reviewer_agent_run_id, final_artifact_id, review_artifact_id,
            evaluator_kind, status, decision, score, failure_reason, failure_stage,
            criteria_json, step_stats_json, proposal_json, summary, recommendation, source
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id;
        """,
        (
            task_run_id,
            manager_agent_run_id,
            reviewer_agent_run_id,
            final_artifact_id,
            review_artifact_id,
            evaluator_kind,
            status,
            decision,
            int(score),
            failure_reason,
            failure_stage,
            safe_json_dumps(criteria),
            safe_json_dumps(step_stats),
            safe_json_dumps(workflow_proposal),
            summary,
            recommendation,
            source,
        ),
    )
    return int(cur.fetchone()["id"])


def fetch_latest_evaluator_for_task(
    cur,
    task_id: int,
    *,
    ensure_evaluator_tables: Callable[[Any], None],
    serialize_evaluator_run_row: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any] | None:
    ensure_evaluator_tables(cur)
    cur.execute(
        """
        SELECT id, task_run_id, manager_agent_run_id, reviewer_agent_run_id, final_artifact_id, review_artifact_id,
               evaluator_kind, status, decision, score, failure_reason, failure_stage,
               criteria_json, step_stats_json, proposal_json, summary, recommendation,
               source, created_at
        FROM evaluator_runs
        WHERE task_run_id = %s
        ORDER BY id DESC
        LIMIT 1;
        """,
        (task_id,),
    )
    row = cur.fetchone()
    return serialize_evaluator_run_row(row) if row else None


def list_workflow_proposals_rows(
    cur,
    *,
    ensure_evaluator_tables: Callable[[Any], None],
    serialize_evaluator_run_row: Callable[[dict[str, Any]], dict[str, Any]],
    serialize_workflow_proposal: Callable[..., dict[str, Any]],
    task_id: int | None = None,
    action_key: str | None = None,
    priority: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    ensure_evaluator_tables(cur)
    clauses: list[str] = ["proposal_json IS NOT NULL", "proposal_json != ''"]
    params: list[Any] = []
    if task_id is not None:
        clauses.append("task_run_id = %s")
        params.append(int(task_id))
    if action_key:
        clauses.append("proposal_json::jsonb ->> 'action_key' = %s")
        params.append(action_key.strip())
    if priority:
        clauses.append("proposal_json::jsonb ->> 'priority' = %s")
        params.append(priority.strip())
    row_limit = max(1, min(int(limit or 20), 200))
    where_sql = f"WHERE {' AND '.join(clauses)}"
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
    rows = [serialize_evaluator_run_row(row) for row in cur.fetchall()]
    return [serialize_workflow_proposal(evaluator_run=row) for row in rows]


def create_agent_message(
    cur,
    task_run_id: int,
    agent_run_id: int | None,
    sender_role: str,
    recipient_role: str,
    message_type: str,
    payload: Any,
    *,
    safe_json_dumps: Callable[[Any], str],
) -> int:
    cur.execute(
        """
        INSERT INTO agent_messages (task_run_id, agent_run_id, sender_role, recipient_role, message_type, payload_json)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id;
        """,
        (task_run_id, agent_run_id, sender_role, recipient_role, message_type, safe_json_dumps(payload)),
    )
    return int(cur.fetchone()["id"])


def create_agent_run(
    cur,
    task_run_id: int,
    role: str,
    status: str,
    *,
    safe_json_dumps: Callable[[Any], str],
    parent_agent_run_id: int | None = None,
    attempt: int = 1,
    brief_artifact_id: int | None = None,
    output_artifact_id: int | None = None,
    review_artifact_id: int | None = None,
    execution_mode: str = "",
    execution_request: Any | None = None,
    source_task_run_id: int | None = None,
    assigned_step_orders: list[int] | None = None,
    assigned_model: str = "",
    assigned_tool_profile: str = "",
    error_summary: str = "",
    started: bool = False,
    completed: bool = False,
) -> int:
    started_at = datetime.now(timezone.utc) if started else None
    completed_at = datetime.now(timezone.utc) if completed else None
    cur.execute(
        """
        INSERT INTO agent_runs (
            task_run_id, parent_agent_run_id, role, status, attempt, brief_artifact_id,
            output_artifact_id, review_artifact_id, execution_mode, execution_request_json,
            source_task_run_id, assigned_step_orders_json, assigned_model, assigned_tool_profile,
            error_summary, created_at, updated_at, started_at, completed_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, %s, %s)
        RETURNING id;
        """,
        (
            task_run_id,
            parent_agent_run_id,
            role,
            status,
            int(attempt),
            brief_artifact_id,
            output_artifact_id,
            review_artifact_id,
            execution_mode,
            safe_json_dumps(execution_request) if execution_request is not None else None,
            source_task_run_id,
            safe_json_dumps(assigned_step_orders or []),
            assigned_model,
            assigned_tool_profile,
            error_summary,
            started_at,
            completed_at,
        ),
    )
    return int(cur.fetchone()["id"])


def build_task_agent_summary_payload(
    *,
    task_id: int,
    agent_rows: list[dict[str, Any]],
    artifact_rows: list[dict[str, Any]],
    serialize_agent_run_row: Callable[[dict[str, Any]], dict[str, Any]],
    multi_agent_protocol_version: str,
    mainline_specialist_execution_modes: set[str],
    latest_evaluator: dict[str, Any] | None = None,
    validation_report: dict[str, Any] | None = None,
    recovery_action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    role_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    specialist_runs: list[dict[str, Any]] = []
    manager_run = None
    reviewer_run = None

    for row in agent_rows:
        role = str(row.get("role") or "unknown")
        status = str(row.get("status") or "unknown")
        role_counts[role] = int(role_counts.get(role, 0)) + 1
        status_counts[status] = int(status_counts.get(status, 0)) + 1
        if role == "manager" and manager_run is None:
            manager_run = row
        elif role == "reviewer" and reviewer_run is None:
            reviewer_run = row
        elif role == "specialist":
            specialist_runs.append(row)

    final_artifacts = [item for item in artifact_rows if item.get("artifact_type") == "final"]
    review_artifacts = [item for item in artifact_rows if item.get("artifact_type") == "review"]
    latest_final = max(
        final_artifacts,
        key=lambda item: (int(item.get("version") or 0), int(item.get("id") or 0)),
        default=None,
    )
    latest_review = max(
        review_artifacts,
        key=lambda item: (int(item.get("version") or 0), int(item.get("id") or 0)),
        default=None,
    )

    latest_final_content = (latest_final or {}).get("content") or {}
    latest_review_content = (latest_review or {}).get("content") or {}
    latest_reviewer_decision = str(
        latest_review_content.get("decision") or latest_final_content.get("review_status") or ""
    )
    latest_decision_source = str(
        latest_review_content.get("decision_source") or latest_final_content.get("decision_source") or ""
    )
    latest_next_strategy = str(latest_final_content.get("next_strategy") or "")

    specialists_completed = (
        all(str(item.get("status") or "") == "completed" for item in specialist_runs)
        if specialist_runs
        else False
    )
    can_execute = bool(specialist_runs) and any(not item.get("output_artifact_id") for item in specialist_runs)
    can_force_rerun = bool(specialist_runs)
    can_finalize = bool(manager_run) and bool(specialist_runs) and specialists_completed
    can_allow_retry = (
        bool(manager_run)
        and str(manager_run.get("status") or "") == "blocked"
        and latest_reviewer_decision == "rework_required"
        and specialists_completed
    )

    awaiting_role = ""
    blocking_reason = ""

    recommended_action = "none"
    if not agent_rows:
        recommended_action = "bootstrap"
        awaiting_role = "operator"
        blocking_reason = "task 还没有 Stage 5 agent runs"
    elif can_allow_retry:
        recommended_action = "finalize_retry"
        awaiting_role = "manager"
        blocking_reason = "reviewer requested rework，等待 manager 重新汇总"
    elif can_execute:
        recommended_action = "execute"
        awaiting_role = "specialist"
        blocking_reason = "specialist outputs 尚未生成"
    elif can_finalize and not latest_final:
        recommended_action = "finalize"
        awaiting_role = "manager"
        blocking_reason = "specialist 已完成，等待 manager 汇总 final artifact"
    elif latest_reviewer_decision == "rejected":
        recommended_action = "escalate_operator"
        awaiting_role = "operator"
        blocking_reason = "reviewer rejected final candidate"
    elif can_force_rerun and latest_reviewer_decision == "rework_required":
        recommended_action = "rerun_specialists"
        awaiting_role = "specialist"
        blocking_reason = "reviewer requested rework，等待 specialist 重跑"

    if not awaiting_role and reviewer_run and str(reviewer_run.get("status") or "") in {"queued", "running"}:
        awaiting_role = "reviewer"
        blocking_reason = "specialist inputs 已就绪，等待 reviewer"
    if not awaiting_role and manager_run and str(manager_run.get("status") or "") == "failed":
        awaiting_role = "operator"
        blocking_reason = str(manager_run.get("error_summary") or "manager failed")

    specialist_summaries = [
        {
            "id": int(item["id"]),
            "status": str(item.get("status") or "unknown"),
            "attempt": int(item.get("attempt") or 1),
            "output_artifact_id": item.get("output_artifact_id"),
            "review_artifact_id": item.get("review_artifact_id"),
            "execution_mode": item.get("execution_mode") or "",
            "subtask_type": str(
                (item.get("execution_request") or {}).get("subtask_type") or "readonly_step_digest"
            ),
            "assigned_step_orders": item.get("assigned_step_orders") or [],
            "has_execution_request": bool(item.get("execution_request")),
            "assigned_model": item.get("assigned_model") or "",
            "assigned_tool_profile": item.get("assigned_tool_profile") or "",
        }
        for item in specialist_runs
    ]
    specialist_execution_modes = sorted(
        {
            str(item.get("execution_mode") or "")
            for item in specialist_runs
            if str(item.get("execution_mode") or "").strip()
        }
    )
    specialist_subtask_types = sorted(
        {
            str((item.get("execution_request") or {}).get("subtask_type") or "readonly_step_digest")
            for item in specialist_runs
        }
    )
    execution_backend = "none"
    implementation_status = "manager_worker_execute_demo"
    record_origin = "uninitialized"
    control_mode = "demo_operate"
    latest_evaluator_source = str((latest_evaluator or {}).get("source") or "")
    latest_workflow_proposal = (latest_evaluator or {}).get("workflow_proposal") or {}
    latest_validation_report = validation_report or {}
    latest_recovery_action = recovery_action or {}
    validation_passed = latest_validation_report.get("passed")
    validation_summary = str(latest_validation_report.get("summary") or "").strip()
    recovery_action_key = str(latest_recovery_action.get("action") or "").strip()
    recovery_summary = str(latest_recovery_action.get("summary") or "").strip()
    runtime_fanout_active = any(mode == "task_runtime_worker_v1" for mode in specialist_execution_modes)
    postrun_observed = any(mode == "task_postrun_readonly_v1" for mode in specialist_execution_modes)
    if (latest_evaluator or {}).get("source") == "task_runtime_postrun_v1" or any(
        mode in mainline_specialist_execution_modes for mode in specialist_execution_modes
    ):
        execution_backend = "mainline"
        implementation_status = "task_runtime_postrun_v1"
        record_origin = (
            "mainline_postrun"
            if (latest_evaluator or {}).get("source") == "task_runtime_postrun_v1" or postrun_observed
            else "mainline_runtime"
        )
        control_mode = "observe_only"
    elif any(mode == "worker_readonly_v1" for mode in specialist_execution_modes):
        execution_backend = "worker"
        record_origin = "worker_demo"
    elif specialist_execution_modes:
        execution_backend = "api"
        record_origin = "api_demo"

    if recovery_action_key and recovery_action_key != "none":
        recommended_action = recovery_action_key
        if not awaiting_role:
            awaiting_role = "operator"
        if not blocking_reason:
            blocking_reason = recovery_summary or validation_summary or "任务级交付校验未通过"

    return {
        "protocol_version": multi_agent_protocol_version,
        "implementation_status": implementation_status,
        "record_origin": record_origin,
        "control_mode": control_mode,
        "task_id": task_id,
        "role_counts": role_counts,
        "status_counts": status_counts,
        "manager": serialize_agent_run_row(manager_run) if manager_run else None,
        "reviewer": serialize_agent_run_row(reviewer_run) if reviewer_run else None,
        "specialists": specialist_summaries,
        "specialist_execution_modes": specialist_execution_modes,
        "specialist_subtask_types": specialist_subtask_types,
        "execution_backend": execution_backend,
        "runtime_fanout_active": runtime_fanout_active,
        "postrun_observed": postrun_observed,
        "latest_final_artifact": {
            "id": latest_final.get("id"),
            "version": int(latest_final.get("version") or 1),
            "review_status": latest_final_content.get("review_status") or "",
            "next_strategy": latest_final_content.get("next_strategy") or "",
            "quality_score": latest_final_content.get("quality_score"),
        }
        if latest_final
        else None,
        "latest_review_artifact": {
            "id": latest_review.get("id"),
            "version": int(latest_review.get("version") or 1),
            "decision": latest_review_content.get("decision") or "",
            "quality_score": latest_review_content.get("quality_score"),
            "decision_source": latest_review_content.get("decision_source") or "",
        }
        if latest_review
        else None,
        "latest_evaluator": latest_evaluator,
        "latest_evaluator_source": latest_evaluator_source,
        "latest_workflow_proposal": latest_workflow_proposal,
        "latest_validation_report": latest_validation_report,
        "latest_recovery_action": latest_recovery_action,
        "validation_passed": validation_passed,
        "validation_summary": validation_summary,
        "recovery_action_key": recovery_action_key,
        "recovery_summary": recovery_summary,
        "latest_workflow_proposal_action": str(latest_workflow_proposal.get("action_key") or ""),
        "latest_workflow_proposal_priority": str(latest_workflow_proposal.get("priority") or ""),
        "latest_recommendation": (latest_evaluator or {}).get("recommendation") or "",
        "latest_failure_reason": (
            "deliverable_validation_failed"
            if validation_passed is False
            else ((latest_evaluator or {}).get("failure_reason") or "none")
        ),
        "latest_failure_stage": (
            "deliverable_validation"
            if validation_passed is False
            else ((latest_evaluator or {}).get("failure_stage") or "none")
        ),
        "history": {
            "final_artifact_versions": len(final_artifacts),
            "review_artifact_versions": len(review_artifacts),
        },
        "capabilities": {
            "can_execute": can_execute,
            "can_force_rerun": can_force_rerun,
            "can_finalize": can_finalize,
            "can_allow_retry": can_allow_retry,
            "can_bootstrap_demo": not agent_rows,
            "demo_actions_recommended": implementation_status != "task_runtime_postrun_v1",
            "runtime_fanout_active": runtime_fanout_active,
        },
        "recommended_action": recommended_action,
        "latest_reviewer_decision": latest_reviewer_decision,
        "latest_decision_source": latest_decision_source,
        "latest_next_strategy": latest_next_strategy,
        "awaiting_role": awaiting_role,
        "blocking_reason": blocking_reason,
    }


def fetch_task_agent_summary(
    cur,
    task_id: int,
    *,
    serialize_agent_run_row: Callable[[dict[str, Any]], dict[str, Any]],
    serialize_agent_artifact_row: Callable[[dict[str, Any]], dict[str, Any]],
    fetch_latest_evaluator_for_task_fn: Callable[[Any, int], dict[str, Any] | None],
    build_task_agent_summary_payload_fn: Callable[..., dict[str, Any]],
    parse_maybe_json: Callable[[Any], Any],
) -> dict[str, Any]:
    cur.execute(
        """
        SELECT validation_report_json, recovery_action_json
        FROM task_runs
        WHERE id = %s;
        """,
        (task_id,),
    )
    task_row = cur.fetchone() or {}
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
    agent_rows = [serialize_agent_run_row(row) for row in cur.fetchall()]
    cur.execute(
        """
        SELECT id, task_run_id, agent_run_id, artifact_type, summary, content_json, version, created_at
        FROM agent_artifacts
        WHERE task_run_id = %s
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    artifact_rows = [serialize_agent_artifact_row(row) for row in cur.fetchall()]
    latest_evaluator = fetch_latest_evaluator_for_task_fn(cur, task_id)
    return build_task_agent_summary_payload_fn(
        task_id=task_id,
        agent_rows=agent_rows,
        artifact_rows=artifact_rows,
        latest_evaluator=latest_evaluator,
        validation_report=parse_maybe_json(task_row.get("validation_report_json")) or {},
        recovery_action=parse_maybe_json(task_row.get("recovery_action_json")) or {},
    )


def build_demo_review_criteria(
    *,
    task_status: str,
    step_rows: list[dict[str, Any]],
    specialist_draft_count: int,
    reviewer_decision: str,
) -> dict[str, Any]:
    total_steps = len(step_rows)
    completed_steps = sum(1 for row in step_rows if row.get("status") == "completed")
    failed_steps = sum(1 for row in step_rows if row.get("status") == "failed")
    pending_steps = max(0, total_steps - completed_steps - failed_steps)
    criteria = [
        {
            "criterion": "specialist_drafts_present",
            "passed": specialist_draft_count > 0,
            "actual": specialist_draft_count,
        },
        {
            "criterion": "task_step_coverage_available",
            "passed": total_steps > 0 or task_status in {"completed", "failed", "waiting_approval"},
            "actual": total_steps,
        },
        {
            "criterion": "reviewer_decision_recorded",
            "passed": reviewer_decision in {"approved", "rework_required", "rejected"},
            "actual": reviewer_decision,
        },
    ]
    score = 100
    if failed_steps:
        score -= min(30, failed_steps * 10)
    if reviewer_decision == "rework_required":
        score -= 25
    elif reviewer_decision == "rejected":
        score -= 45
    if specialist_draft_count == 0:
        score -= 40
    score = max(0, min(100, score))
    return {
        "criteria": criteria,
        "score": score,
        "step_stats": {
            "total_steps": total_steps,
            "completed_steps": completed_steps,
            "failed_steps": failed_steps,
            "pending_steps": pending_steps,
        },
    }


def derive_evaluator_failure_profile(
    *,
    task_status: str,
    step_rows: list[dict[str, Any]],
    specialist_draft_count: int,
    reviewer_decision: str,
) -> dict[str, str]:
    total_steps = len(step_rows)
    completed_steps = sum(1 for row in step_rows if row.get("status") == "completed")
    failed_steps = sum(1 for row in step_rows if row.get("status") == "failed")

    if reviewer_decision == "approved":
        return {
            "failure_reason": "none",
            "failure_stage": "none",
            "recommendation": "当前质量门通过，可以继续推进下一阶段或扩展 evaluator 自动反馈。",
            "summary": "evaluator 判定当前结果健康，可继续推进。",
        }
    if failed_steps > 0 or task_status == "failed":
        return {
            "failure_reason": "task_failed_step",
            "failure_stage": "execution",
            "recommendation": "优先检查 failed steps 的错误摘要，修复输入或步骤依赖后再执行。",
            "summary": "evaluator 发现任务执行阶段存在 failed step。",
        }
    if specialist_draft_count == 0:
        return {
            "failure_reason": "missing_specialist_outputs",
            "failure_stage": "specialist",
            "recommendation": "需要先补齐 specialist outputs，再让 manager/reviewer 继续收敛。",
            "summary": "evaluator 发现 specialist outputs 缺失，无法形成有效汇总。",
        }
    if total_steps > 0 and completed_steps < total_steps:
        return {
            "failure_reason": "incomplete_execution",
            "failure_stage": "execution",
            "recommendation": "补齐 pending/running steps 后重新生成 drafts 并再次评估。",
            "summary": "evaluator 发现任务执行尚未完成，结果需要返工。",
        }
    if reviewer_decision == "rejected":
        return {
            "failure_reason": "reviewer_rejected",
            "failure_stage": "review",
            "recommendation": "需要 operator 接管并重新规划，再决定是否继续拆解执行。",
            "summary": "evaluator 根据 reviewer 拒绝结果要求人工接管。",
        }
    if reviewer_decision == "rework_required":
        return {
            "failure_reason": "reviewer_requested_rework",
            "failure_stage": "review",
            "recommendation": "按 reviewer 建议返工 specialists 或允许 manager retry 后重新评估。",
            "summary": "evaluator 根据 reviewer 返工结果要求继续补强输出。",
        }
    return {
        "failure_reason": "unknown",
        "failure_stage": "unknown",
        "recommendation": "需要人工检查当前 evaluator 输出与任务上下文。",
        "summary": "evaluator 无法归类当前失败原因。",
    }


def build_workflow_proposal(
    *,
    task_id: int,
    reviewer_decision: str,
    failure_profile: dict[str, str],
    quality_bundle: dict[str, Any],
    next_strategy: str,
) -> dict[str, Any]:
    failure_reason = str(failure_profile.get("failure_reason") or "unknown")
    failure_stage = str(failure_profile.get("failure_stage") or "unknown")
    recommendation = str(failure_profile.get("recommendation") or "").strip()
    score = int((quality_bundle.get("score") or 0))

    priority = "medium"
    target_surface = "stage5_orchestration"
    action_key = "inspect_manually"
    title = "人工检查当前闭环"
    action_payload: dict[str, Any] = {"recommended_action": "inspect_manually"}

    if failure_reason == "none":
        priority = "low"
        target_surface = "stage6_evaluator"
        action_key = "expand_specialist_scope"
        title = "扩展 specialist 子任务覆盖面"
        action_payload = {
            "recommended_action": "expand_specialist_scope",
            "candidate_subtasks": ["readonly_source_snapshot"],
            "trigger": "quality_gate_passed",
        }
    elif failure_reason == "task_failed_step":
        priority = "high"
        target_surface = "task_runtime"
        action_key = "repair_failed_steps"
        title = "修复 failed steps 后重跑主任务"
        action_payload = {
            "recommended_action": "repair_failed_steps",
            "retry_scope": "task_steps",
            "expected_next_strategy": "resume_task",
        }
    elif failure_reason == "missing_specialist_outputs":
        priority = "high"
        target_surface = "stage5_specialists"
        action_key = "queue_specialists"
        title = "补齐 specialist outputs"
        action_payload = {
            "recommended_action": "queue_specialists",
            "dispatch": "execute_worker_demo",
            "expected_next_strategy": "generate_drafts",
        }
    elif failure_reason == "incomplete_execution":
        priority = "high"
        target_surface = "stage5_specialists"
        action_key = "rerun_incomplete_specialists"
        title = "重跑未完成 specialist"
        action_payload = {
            "recommended_action": "rerun_incomplete_specialists",
            "dispatch": "execute_worker_demo",
            "force_rerun": True,
        }
    elif failure_reason == "reviewer_rejected":
        priority = "high"
        target_surface = "operator_escalation"
        action_key = "escalate_to_operator"
        title = "升级 operator 重新规划"
        action_payload = {
            "recommended_action": "escalate_to_operator",
            "expected_next_strategy": "replan_task",
        }
    elif failure_reason == "reviewer_requested_rework":
        priority = "medium"
        target_surface = "stage5_manager_retry"
        action_key = "rerun_specialists_then_finalize"
        title = "重跑 specialists 后再次 finalize"
        action_payload = {
            "recommended_action": "rerun_specialists_then_finalize",
            "dispatch": "execute_worker_demo",
            "followed_by": "finalize_demo_allow_retry",
        }

    return {
        "version": "stage6-workflow-proposal-v1",
        "task_id": task_id,
        "status": "suggested",
        "decision": reviewer_decision,
        "score": score,
        "failure_reason": failure_reason,
        "failure_stage": failure_stage,
        "next_strategy": next_strategy,
        "priority": priority,
        "target_surface": target_surface,
        "action_key": action_key,
        "title": title,
        "rationale": recommendation,
        "action_payload": action_payload,
        "auto_apply_eligible": False,
    }


def resolve_reviewer_decision(
    *,
    requested_decision: str,
    task_status: str,
    step_rows: list[dict[str, Any]],
    specialist_draft_count: int,
) -> tuple[str, str]:
    normalized = str(requested_decision or "").strip().lower() or "auto"
    if normalized != "auto":
        return normalized, "manual"

    total_steps = len(step_rows)
    completed_steps = sum(1 for row in step_rows if row.get("status") == "completed")
    failed_steps = sum(1 for row in step_rows if row.get("status") == "failed")

    if failed_steps > 0 or task_status == "failed":
        return "rejected", "auto"
    if specialist_draft_count == 0:
        return "rework_required", "auto"
    if total_steps > 0 and completed_steps < total_steps:
        return "rework_required", "auto"
    return "approved", "auto"


def build_specialist_execution_request(
    *,
    slot: int,
    manager_objective: str,
    assigned_steps: list[dict[str, Any]] | None = None,
    brief_artifact_id: int | None = None,
    plan_artifact_id: int | None = None,
    note: str = "",
    execution_mode: str = "api_readonly_subtask_v1",
    subtask_type: str = "readonly_step_digest",
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assigned_steps = assigned_steps or []
    assigned_step_orders = [
        int(step.get("step_order") or 0) for step in assigned_steps if int(step.get("step_order") or 0) > 0
    ]
    source = source or {}
    focus_questions = [
        "这个子问题最关键的信息是什么",
        "有哪些明显缺口、风险或需要继续跟进的点",
    ]
    deliverable = f"specialist-{slot} readonly digest"
    scope = "plan_boundary_digest" if slot == 1 else "risk_result_digest"
    success_criteria = [
        "summarize assigned steps",
        "highlight risks and gaps",
        "produce manager-consumable digest",
    ]
    if subtask_type == "readonly_source_snapshot":
        deliverable = "readonly source snapshot"
        scope = "source_snapshot"
        success_criteria = [
            "return source metadata",
            "return a bounded excerpt or selected fields",
            "highlight gaps and risks",
        ]
    elif subtask_type == "readonly_task_snapshot":
        deliverable = "readonly task snapshot"
        scope = "task_snapshot"
        success_criteria = [
            "return bounded task-level status snapshot",
            "include latest evaluation and review signals",
            "highlight next operator or manager action",
        ]
    return {
        "execution_mode": execution_mode,
        "tool_profile": "specialist-readonly",
        "subtask_type": subtask_type,
        "slot": slot,
        "objective": manager_objective,
        "scope": scope,
        "deliverable": deliverable,
        "assigned_step_orders": assigned_step_orders,
        "source": source,
        "focus_questions": focus_questions,
        "evidence_refs": [
            {"artifact_id": artifact_id, "label": label}
            for artifact_id, label in [
                (brief_artifact_id, "specialist_brief"),
                (plan_artifact_id, "manager_plan"),
            ]
            if artifact_id
        ],
        "constraints": ["readonly-only", "do-not-write-files", "do-not-emit-final-answer"],
        "success_criteria": success_criteria,
        "note": note,
    }


def build_specialist_step_partitions(
    *,
    step_rows: list[dict[str, Any]],
    specialist_count: int,
    task_row: dict[str, Any],
    build_task_display_input_excerpt: Callable[[dict[str, Any]], str],
    build_task_result_excerpt: Callable[[dict[str, Any]], str],
) -> tuple[list[dict[str, Any]], list[list[dict[str, Any]]], dict[str, int]]:
    step_outline = [
        {
            "step_order": int(row["step_order"]),
            "step_name": row["step_name"],
            "status": row["status"],
            "tool_name": row.get("tool_name") or "",
        }
        for row in step_rows[:6]
    ]
    specialist_step_partitions: list[list[dict[str, Any]]] = [[] for _ in range(max(1, specialist_count))]
    if step_rows:
        for index, step_row in enumerate(step_rows):
            specialist_step_partitions[index % len(specialist_step_partitions)].append(
                {
                    "step_order": int(step_row["step_order"]),
                    "step_name": step_row["step_name"],
                    "status": step_row["status"],
                    "tool_name": step_row.get("tool_name") or "",
                    "input_excerpt": str(step_row.get("input_payload") or "")[:180],
                    "output_excerpt": str(step_row.get("output_payload") or "")[:220],
                    "error_excerpt": str(step_row.get("error_message") or "")[:160],
                }
            )
    else:
        specialist_step_partitions = [
            [
                {
                    "step_order": 0,
                    "step_name": "task-result-fallback",
                    "status": task_row["status"],
                    "tool_name": "",
                    "input_excerpt": build_task_display_input_excerpt(task_row),
                    "output_excerpt": build_task_result_excerpt(task_row),
                    "error_excerpt": str(task_row.get("error_message") or "")[:160],
                }
            ]
            for _ in specialist_step_partitions
        ]
    step_status_counts: dict[str, int] = {}
    for row in step_rows:
        status_key = str(row.get("status") or "unknown")
        step_status_counts[status_key] = int(step_status_counts.get(status_key, 0)) + 1
    return step_outline, specialist_step_partitions, step_status_counts


def build_specialist_draft_payload(
    *,
    slot: int,
    task_id: int,
    agent_run_id: int,
    manager_objective: str,
    task_row: dict[str, Any],
    step_outline: list[dict[str, Any]],
    assigned_steps: list[dict[str, Any]],
    plan_artifact_id: int | None,
    note: str,
    step_status_counts: dict[str, int],
    multi_agent_protocol_version: str,
    execution_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assigned_completed_steps = sum(1 for step in assigned_steps if step.get("status") == "completed")
    assigned_failed_steps = sum(1 for step in assigned_steps if step.get("status") == "failed")
    assigned_pending_steps = max(0, len(assigned_steps) - assigned_completed_steps - assigned_failed_steps)
    assigned_step_orders = [
        int(step.get("step_order") or 0) for step in assigned_steps if int(step.get("step_order") or 0) > 0
    ]
    completed_names = [str(step.get("step_name") or "") for step in assigned_steps if step.get("status") == "completed"]
    failed_names = [str(step.get("step_name") or "") for step in assigned_steps if step.get("status") == "failed"]
    pending_names = [
        str(step.get("step_name") or "")
        for step in assigned_steps
        if step.get("status") not in {"completed", "failed"}
    ]
    output_digest = [
        {
            "step_order": int(step.get("step_order") or 0),
            "step_name": step.get("step_name") or "",
            "status": step.get("status") or "unknown",
            "tool_name": step.get("tool_name") or "",
            "output_excerpt": step.get("output_excerpt") or "",
        }
        for step in assigned_steps[:3]
        if step.get("output_excerpt")
    ]
    risk_digest = [
        {
            "step_order": int(step.get("step_order") or 0),
            "step_name": step.get("step_name") or "",
            "status": step.get("status") or "unknown",
            "error_excerpt": step.get("error_excerpt") or "",
        }
        for step in assigned_steps
        if step.get("status") == "failed" or step.get("error_excerpt")
    ][:3]
    observations = [
        f"step#{int(step.get('step_order') or 0)} {step.get('step_name') or ''} -> {step.get('status') or 'unknown'}"
        for step in assigned_steps[:4]
    ]
    recommended_followups: list[str] = []
    if assigned_failed_steps:
        recommended_followups.append("优先检查 failed steps 的错误摘要并决定是否重试")
    if assigned_pending_steps:
        recommended_followups.append("补齐 pending/running steps 后再重新汇总")
    if not recommended_followups:
        recommended_followups.append("基于当前已完成步骤继续汇总为 manager final candidate")
    execution_result = {
        "execution_mode": "api_readonly_subtask_v1",
        "subtask_type": "readonly_step_digest",
        "status": "completed",
        "request_snapshot": execution_request or {},
        "assigned_step_orders": assigned_step_orders,
        "completed_step_names": completed_names[:6],
        "failed_step_names": failed_names[:6],
        "pending_step_names": pending_names[:6],
        "observations": observations,
        "output_digest": output_digest,
        "risk_digest": risk_digest,
        "recommended_followups": recommended_followups,
    }
    return {
        "protocol_version": multi_agent_protocol_version,
        "task_id": task_id,
        "agent_run_id": agent_run_id,
        "summary": f"子问题 {slot} 完成只读 specialist 子任务并生成结构化 draft",
        "output": {
            "slot": slot,
            "deliverable": f"Draft for subtask {slot}",
            "objective": manager_objective,
            "task_status": task_row["status"],
            "task_result_excerpt": str(task_row.get("result") or "")[:280],
            "task_error_excerpt": str(task_row.get("error_message") or "")[:200],
            "step_outline": step_outline,
            "assigned_steps": assigned_steps,
            "subtask": {
                "type": "readonly_step_digest",
                "execution_mode": "api_readonly_subtask_v1",
                "assigned_step_orders": assigned_step_orders,
            },
            "execution_request": execution_request or {},
            "execution_result": execution_result,
            "execution_summary": {
                "assigned_step_count": len(assigned_steps),
                "assigned_completed_steps": assigned_completed_steps,
                "assigned_failed_steps": assigned_failed_steps,
                "assigned_pending_steps": assigned_pending_steps,
                "step_status_counts": {
                    "completed": assigned_completed_steps,
                    "failed": assigned_failed_steps,
                    "other": assigned_pending_steps,
                },
            },
            "focus": "梳理计划与任务边界" if slot == 1 else "汇总执行结果与剩余风险",
        },
        "evidence_refs": [{"artifact_id": plan_artifact_id, "label": "manager_plan"}] if plan_artifact_id else [],
        "known_gaps": [] if task_row["status"] == "completed" else [f"task 当前状态为 {task_row['status']}"],
        "quality_signals": {
            "task_status": task_row["status"],
            "global_step_status_counts": step_status_counts,
            "specialist_execution_mode": "api_readonly_subtask_v1",
            "assigned_step_count": len(assigned_steps),
        },
        "note": note,
    }
