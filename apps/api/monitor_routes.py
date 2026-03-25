from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import APIRouter, Header


def build_monitor_overview_response(
    *,
    overview_snapshot: dict[str, Any],
    stage56_metrics: dict[str, Any],
    stage7_metrics: dict[str, Any],
    redis_stats: dict[str, Any],
    readiness_metrics: dict[str, Any],
    default_enforced_change_target_types: set[str],
    change_gate_required_target_types: set[str],
    step_request_protocol_version: str,
    multi_agent_protocol_version: str,
    runtime_version_metadata: dict[str, Any],
) -> dict[str, Any]:
    tasks_by_status = overview_snapshot["tasks_by_status"]
    agent_runs_by_status = overview_snapshot["agent_runs_by_status"]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "task_metrics": {
            "total_tasks": overview_snapshot["total_tasks"],
            "checkpointed_tasks": overview_snapshot["checkpointed_tasks"],
            "tasks_by_status": tasks_by_status,
        },
        "session_metrics": {
            "total_sessions": overview_snapshot["total_sessions"],
            "total_memories": overview_snapshot["total_memories"],
            "total_session_states": overview_snapshot["total_session_states"],
            "total_session_reviews": overview_snapshot["total_session_reviews"],
        },
        "review_metrics": {
            "daily_reviews_today": overview_snapshot["daily_reviews_today"],
            "last_daily_review_at": overview_snapshot["last_daily_review_at"],
        },
        "approval_metrics": {
            "pending_approvals": overview_snapshot["pending_approvals"],
        },
        "queue_metrics": redis_stats,
        "risk_metrics": {
            "risk_policy_count": overview_snapshot["risk_policy_count"],
        },
        "tool_metrics": {
            "tool_registry_count": overview_snapshot["tool_registry_count"],
            "disabled_tool_count": overview_snapshot["disabled_tool_count"],
        },
        "model_metrics": {
            "model_provider_count": overview_snapshot["model_provider_count"],
            "disabled_model_provider_count": overview_snapshot["disabled_model_provider_count"],
            "model_route_count": overview_snapshot["model_route_count"],
            "disabled_model_route_count": overview_snapshot["disabled_model_route_count"],
        },
        "change_metrics": {
            "total_change_requests": overview_snapshot["total_change_requests"],
            "pending_change_requests": overview_snapshot["pending_change_requests"],
            "approved_change_requests": overview_snapshot["approved_change_requests"],
            "rejected_change_requests": overview_snapshot["rejected_change_requests"],
            "applied_change_requests": overview_snapshot["applied_change_requests"],
            "closed_change_requests": overview_snapshot["closed_change_requests"],
            "change_request_closure_ratio": overview_snapshot["change_request_closure_ratio"],
            "enforced_target_types": sorted(default_enforced_change_target_types),
            "enforced_target_count": len(default_enforced_change_target_types),
            "required_gate_target_types": sorted(change_gate_required_target_types),
            "required_gate_target_count": len(change_gate_required_target_types),
        },
        "access_metrics": {
            "actor_count": overview_snapshot["access_actor_count"],
            "quota_count": overview_snapshot["access_quota_count"],
            "quota_pressure_count": overview_snapshot["quota_pressure_count"],
            "actors_by_role": overview_snapshot["actors_by_role"],
        },
        "runtime_metadata": {
            "step_request_protocol_version": step_request_protocol_version,
            "multi_agent_protocol_version": multi_agent_protocol_version,
            "version": runtime_version_metadata,
        },
        "agent_metrics": {
            "total_agent_runs": overview_snapshot["total_agent_runs"],
            "running_agent_runs": int(agent_runs_by_status.get("running", 0)),
            "blocked_agent_runs": int(agent_runs_by_status.get("blocked", 0)),
            "agent_runs_by_status": agent_runs_by_status,
            "agent_runs_by_role": overview_snapshot["agent_runs_by_role"],
            "total_agent_messages": overview_snapshot["total_agent_messages"],
            "total_agent_artifacts": overview_snapshot["total_agent_artifacts"],
            "stage5_task_count": len(stage56_metrics["stage5_summary_rows"]),
            "specialist_subtasks_by_type": stage56_metrics["specialist_subtasks_by_type"],
            "tasks_requiring_execute": stage56_metrics["tasks_requiring_execute"],
            "tasks_requiring_finalize": stage56_metrics["tasks_requiring_finalize"],
            "tasks_requiring_retry": stage56_metrics["tasks_requiring_retry"],
            "tasks_requiring_operator_escalation": stage56_metrics["tasks_requiring_operator_escalation"],
        },
        "evaluator_metrics": {
            "total_evaluator_runs": overview_snapshot["total_evaluator_runs"],
            "avg_score": overview_snapshot["avg_evaluator_score"],
            "runs_by_decision": overview_snapshot["evaluator_runs_by_decision"],
            "runs_by_reason": overview_snapshot["evaluator_runs_by_reason"],
            "total_workflow_proposals": overview_snapshot["total_workflow_proposals"],
            "workflow_proposals_by_action": overview_snapshot["workflow_proposals_by_action"],
            "workflow_proposals_by_priority": overview_snapshot["workflow_proposals_by_priority"],
        },
        "readiness_metrics": readiness_metrics,
        "recent_audit_logs": overview_snapshot["recent_audit_logs"],
        "recent_tasks": overview_snapshot["recent_tasks"],
        "recent_reviews": overview_snapshot["recent_reviews"],
        "recent_agent_runs": overview_snapshot["recent_agent_runs"],
        "recent_evaluator_runs": overview_snapshot["recent_evaluator_runs"],
        "recent_workflow_proposals": overview_snapshot["workflow_proposal_rows"],
    }


def register_monitor_routes(
    *,
    get_conn: Callable[[], Any],
    require_actor_permission: Callable[[Any, str | None, str], dict[str, Any]],
    ensure_risk_policies_table: Callable[[Any], None],
    ensure_access_actors_table: Callable[[Any], None],
    ensure_access_quotas_table: Callable[[Any], None],
    ensure_tool_registry_table: Callable[[Any], None],
    ensure_model_providers_table: Callable[[Any], None],
    ensure_model_routes_table: Callable[[Any], None],
    ensure_change_requests_table: Callable[[Any], None],
    ensure_agent_tables: Callable[[Any], None],
    fetch_monitor_overview_snapshot: Callable[..., dict[str, Any]],
    build_task_display_user_input: Callable[[dict[str, Any]], dict[str, Any]],
    extract_task_clarification_state: Callable[[dict[str, Any]], dict[str, Any]],
    parse_maybe_json: Callable[[Any], Any],
    serialize_session_review_row: Callable[[dict[str, Any]], dict[str, Any]],
    serialize_agent_run_row: Callable[[dict[str, Any]], dict[str, Any]],
    serialize_evaluator_run_row: Callable[[dict[str, Any]], dict[str, Any]],
    list_workflow_proposals_rows: Callable[..., list[dict[str, Any]]],
    fetch_stage56_overview_metrics: Callable[..., dict[str, Any]],
    fetch_task_agent_summary: Callable[[Any, int], dict[str, Any]],
    mainline_specialist_execution_modes: list[str],
    mainline_specialist_tool_profiles: list[str],
    fetch_stage7_overview_metrics: Callable[[Any], dict[str, Any]],
    get_redis_monitor_stats: Callable[[], dict[str, Any]],
    compute_stage_readiness_metrics: Callable[..., dict[str, Any]],
    default_enforced_change_target_types: set[str],
    change_gate_required_target_types: set[str],
    step_request_protocol_version: str,
    multi_agent_protocol_version: str,
    get_runtime_version_metadata: Callable[[], dict[str, Any]],
):
    router = APIRouter()

    @router.get("/monitor/overview")
    def get_monitor_overview(x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        ensure_risk_policies_table(cur)
        ensure_access_actors_table(cur)
        ensure_access_quotas_table(cur)
        ensure_tool_registry_table(cur)
        ensure_model_providers_table(cur)
        ensure_model_routes_table(cur)
        ensure_change_requests_table(cur)
        ensure_agent_tables(cur)
        conn.commit()
        overview_snapshot = fetch_monitor_overview_snapshot(
            cur,
            build_task_display_user_input_fn=build_task_display_user_input,
            extract_task_clarification_state_fn=extract_task_clarification_state,
            parse_maybe_json_fn=parse_maybe_json,
            serialize_session_review_row_fn=serialize_session_review_row,
            serialize_agent_run_row_fn=serialize_agent_run_row,
            serialize_evaluator_run_row_fn=serialize_evaluator_run_row,
            list_workflow_proposals_rows_fn=list_workflow_proposals_rows,
        )
        stage56_metrics = fetch_stage56_overview_metrics(
            cur,
            fetch_task_agent_summary_fn=fetch_task_agent_summary,
            specialist_execution_modes=list(mainline_specialist_execution_modes),
            specialist_tool_profiles=list(mainline_specialist_tool_profiles),
        )
        stage7_metrics = fetch_stage7_overview_metrics(cur)
        cur.close()
        conn.close()

        readiness_metrics = compute_stage_readiness_metrics(
            total_sessions=overview_snapshot["total_sessions"],
            total_session_states=overview_snapshot["total_session_states"],
            total_session_reviews=overview_snapshot["total_session_reviews"],
            active_session_count=overview_snapshot["active_session_count"],
            sessions_missing_state_count=overview_snapshot["sessions_missing_state_count"],
            sessions_missing_review_count=overview_snapshot["sessions_missing_review_count"],
            sessions_needing_review_count=overview_snapshot["sessions_needing_review_count"],
            sessions_with_duplicate_memories_count=overview_snapshot["sessions_with_duplicate_memories_count"],
            sessions_with_open_loops_count=overview_snapshot["sessions_with_open_loops_count"],
            access_actor_count=overview_snapshot["access_actor_count"],
            access_quota_count=overview_snapshot["access_quota_count"],
            quota_pressure_count=overview_snapshot["quota_pressure_count"],
            change_request_total_count=overview_snapshot["total_change_requests"],
            change_request_pending_count=overview_snapshot["pending_change_requests"],
            change_request_approved_count=overview_snapshot["approved_change_requests"],
            change_request_rejected_count=overview_snapshot["rejected_change_requests"],
            change_request_applied_count=overview_snapshot["applied_change_requests"],
            stage5_mainline_task_count=stage56_metrics["stage5_mainline_task_count"],
            stage5_runtime_fanout_task_count=stage56_metrics["stage5_runtime_fanout_task_count"],
            stage5_role_skeleton_ready_count=stage56_metrics["stage5_role_skeleton_ready_count"],
            stage5_terminal_mainline_task_count=stage56_metrics["stage5_terminal_mainline_task_count"],
            stage5_terminal_ready_count=stage56_metrics["stage5_terminal_ready_count"],
            stage6_mainline_evaluator_run_count=stage56_metrics["stage6_mainline_evaluator_run_count"],
            stage6_mainline_workflow_proposal_count=stage56_metrics["stage6_mainline_workflow_proposal_count"],
            stage6_auto_mapped_proposal_count=stage56_metrics["stage6_auto_mapped_proposal_count"],
            stage6_mainline_bridged_change_request_count=stage56_metrics["stage6_mainline_bridged_change_request_count"],
            stage5_non_readonly_specialist_task_count=stage56_metrics["stage5_non_readonly_specialist_task_count"],
            stage5_runtime_fanout_event_count=stage56_metrics["stage5_runtime_fanout_event_count"],
            stage5_runtime_fanin_event_count=stage56_metrics["stage5_runtime_fanin_event_count"],
            stage5_runtime_execute_event_count=stage56_metrics["stage5_runtime_execute_event_count"],
            stage6_failure_taxonomy_count=stage56_metrics["stage6_failure_taxonomy_count"],
            stage6_shadow_validation_count=stage56_metrics["stage6_shadow_validation_count"],
            stage7_workflow_improvement_change_request_count=stage7_metrics["stage7_workflow_improvement_change_request_count"],
            stage7_shadow_required_change_request_count=stage7_metrics["stage7_shadow_required_change_request_count"],
            stage7_shadow_completed_change_request_count=stage7_metrics["stage7_shadow_completed_change_request_count"],
            stage7_candidate_overlay_validation_count=stage7_metrics["stage7_candidate_overlay_validation_count"],
            stage7_candidate_match_change_request_count=stage7_metrics["stage7_candidate_match_change_request_count"],
            stage7_patch_artifact_ready_count=stage7_metrics["stage7_patch_artifact_ready_count"],
            stage7_rollback_ready_count=stage7_metrics["stage7_rollback_ready_count"],
            stage7_rollback_change_request_count=stage7_metrics["stage7_rollback_change_request_count"],
            stage7_rollback_applied_count=stage7_metrics["stage7_rollback_applied_count"],
            stage7_sandbox_file_applied_count=stage7_metrics["stage7_sandbox_file_applied_count"],
            stage7_sandbox_source_copy_applied_count=stage7_metrics["stage7_sandbox_source_copy_applied_count"],
            stage7_sandbox_source_patch_applied_count=stage7_metrics["stage7_sandbox_source_patch_applied_count"],
            stage7_sandbox_acceptance_passed_count=stage7_metrics["stage7_sandbox_acceptance_passed_count"],
            stage7_sandbox_acceptance_failed_count=stage7_metrics["stage7_sandbox_acceptance_failed_count"],
            stage7_sandbox_auto_rollback_applied_count=stage7_metrics["stage7_sandbox_auto_rollback_applied_count"],
        )
        return build_monitor_overview_response(
            overview_snapshot=overview_snapshot,
            stage56_metrics=stage56_metrics,
            stage7_metrics=stage7_metrics,
            redis_stats=get_redis_monitor_stats(),
            readiness_metrics=readiness_metrics,
            default_enforced_change_target_types=default_enforced_change_target_types,
            change_gate_required_target_types=change_gate_required_target_types,
            step_request_protocol_version=step_request_protocol_version,
            multi_agent_protocol_version=multi_agent_protocol_version,
            runtime_version_metadata=get_runtime_version_metadata(),
        )

    return router
