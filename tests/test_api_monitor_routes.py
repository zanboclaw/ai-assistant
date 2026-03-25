from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import monitor_routes


class MonitorCursor:
    def close(self):
        return None


class MonitorConn:
    def __init__(self):
        self._cursor = MonitorCursor()
        self.commit_called = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commit_called += 1

    def close(self):
        return None


def build_client():
    conn = MonitorConn()
    overview_snapshot = {
        "tasks_by_status": {"completed": 4},
        "total_tasks": 6,
        "total_sessions": 3,
        "total_memories": 8,
        "total_session_states": 2,
        "total_session_reviews": 2,
        "sessions_missing_state_count": 1,
        "sessions_missing_review_count": 1,
        "active_session_count": 2,
        "sessions_needing_review_count": 1,
        "sessions_with_duplicate_memories_count": 0,
        "sessions_with_open_loops_count": 1,
        "daily_reviews_today": 1,
        "pending_approvals": 2,
        "risk_policy_count": 5,
        "tool_registry_count": 6,
        "disabled_tool_count": 1,
        "model_route_count": 4,
        "disabled_model_route_count": 1,
        "model_provider_count": 3,
        "disabled_model_provider_count": 1,
        "total_change_requests": 7,
        "pending_change_requests": 2,
        "approved_change_requests": 2,
        "rejected_change_requests": 1,
        "applied_change_requests": 2,
        "closed_change_requests": 3,
        "change_request_closure_ratio": 0.5,
        "access_actor_count": 2,
        "access_quota_count": 2,
        "quota_pressure_count": 1,
        "actors_by_role": {"admin": 1, "operator": 1},
        "checkpointed_tasks": 1,
        "recent_audit_logs": [{"id": 1}],
        "recent_tasks": [{"id": 11}],
        "total_agent_runs": 5,
        "agent_runs_by_status": {"running": 1, "blocked": 1},
        "agent_runs_by_role": {"manager": 1, "specialist": 4},
        "total_agent_messages": 9,
        "total_agent_artifacts": 4,
        "recent_reviews": [{"id": 71}],
        "recent_agent_runs": [{"id": 81}],
        "total_evaluator_runs": 4,
        "evaluator_runs_by_decision": {"accept": 2},
        "evaluator_runs_by_reason": {"none": 2},
        "avg_evaluator_score": 92.5,
        "recent_evaluator_runs": [{"id": 91}],
        "workflow_proposal_rows": [{"proposal_id": 101}],
        "workflow_proposals_by_action": {"model_route_patch": 1},
        "workflow_proposals_by_priority": {"high": 1},
        "total_workflow_proposals": 1,
        "last_daily_review_at": "2026-03-24T00:00:00+00:00",
    }
    stage56_metrics = {
        "stage5_summary_rows": [{"task_id": 1}],
        "tasks_requiring_execute": 1,
        "tasks_requiring_finalize": 2,
        "tasks_requiring_retry": 0,
        "tasks_requiring_operator_escalation": 1,
        "stage5_mainline_task_count": 1,
        "stage5_runtime_fanout_task_count": 1,
        "stage5_role_skeleton_ready_count": 1,
        "stage5_terminal_mainline_task_count": 1,
        "stage5_terminal_ready_count": 1,
        "stage5_non_readonly_specialist_task_count": 0,
        "specialist_subtasks_by_type": {"readonly_step_digest": 2},
        "stage6_mainline_evaluator_run_count": 1,
        "stage6_mainline_workflow_proposal_count": 1,
        "stage6_auto_mapped_proposal_count": 1,
        "stage6_mainline_bridged_change_request_count": 1,
        "stage5_runtime_fanout_event_count": 1,
        "stage5_runtime_fanin_event_count": 1,
        "stage5_runtime_execute_event_count": 1,
        "stage6_shadow_validation_count": 1,
        "stage6_failure_taxonomy_count": 0,
    }
    stage7_metrics = {
        "stage7_workflow_improvement_change_request_count": 1,
        "stage7_shadow_required_change_request_count": 1,
        "stage7_shadow_completed_change_request_count": 1,
        "stage7_candidate_overlay_validation_count": 1,
        "stage7_candidate_match_change_request_count": 1,
        "stage7_patch_artifact_ready_count": 1,
        "stage7_rollback_ready_count": 1,
        "stage7_rollback_change_request_count": 1,
        "stage7_rollback_applied_count": 0,
        "stage7_sandbox_file_applied_count": 0,
        "stage7_sandbox_source_copy_applied_count": 0,
        "stage7_sandbox_source_patch_applied_count": 0,
        "stage7_sandbox_acceptance_passed_count": 1,
        "stage7_sandbox_acceptance_failed_count": 0,
        "stage7_sandbox_auto_rollback_applied_count": 0,
    }

    app = FastAPI()
    app.include_router(
        monitor_routes.register_monitor_routes(
            get_conn=lambda: conn,
            require_actor_permission=lambda _cur, actor_name, permission: {
                "actor_name": actor_name or "local_admin",
                "permission": permission,
            },
            ensure_risk_policies_table=lambda _cur: None,
            ensure_access_actors_table=lambda _cur: None,
            ensure_access_quotas_table=lambda _cur: None,
            ensure_tool_registry_table=lambda _cur: None,
            ensure_model_providers_table=lambda _cur: None,
            ensure_model_routes_table=lambda _cur: None,
            ensure_change_requests_table=lambda _cur: None,
            ensure_agent_tables=lambda _cur: None,
            fetch_monitor_overview_snapshot=lambda _cur, **_kwargs: overview_snapshot,
            build_task_display_user_input=lambda row: row,
            extract_task_clarification_state=lambda row: row,
            parse_maybe_json=lambda value: value,
            serialize_session_review_row=lambda row: dict(row),
            serialize_agent_run_row=lambda row: dict(row),
            serialize_evaluator_run_row=lambda row: dict(row),
            list_workflow_proposals_rows=lambda _cur, **_kwargs: [],
            fetch_stage56_overview_metrics=lambda _cur, **_kwargs: stage56_metrics,
            fetch_task_agent_summary=lambda _cur, task_id: {"task_id": task_id},
            mainline_specialist_execution_modes=["task_runtime_worker_v1"],
            mainline_specialist_tool_profiles=["readonly"],
            fetch_stage7_overview_metrics=lambda _cur: stage7_metrics,
            get_redis_monitor_stats=lambda: {"queue_length": 3},
            compute_stage_readiness_metrics=lambda **kwargs: {"stage5": kwargs["stage5_mainline_task_count"], "stage7": kwargs["stage7_patch_artifact_ready_count"]},
            default_enforced_change_target_types={"tool_registry"},
            change_gate_required_target_types={"model_route"},
            step_request_protocol_version="stage2-v1",
            multi_agent_protocol_version="multi-agent-v1",
            get_runtime_version_metadata=lambda: {
                "current_version": "stage7-foundation",
                "git_short_commit": "abc123def456",
                "git_branch": "master",
                "git_dirty": False,
                "build_timestamp": "2026-03-25T00:00:00+00:00",
            },
        )
    )
    return TestClient(app), conn


def test_monitor_routes_overview_assembles_metrics():
    client, conn = build_client()

    response = client.get("/monitor/overview", headers={"X-Actor-Name": "local_admin"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_metrics"]["total_tasks"] == 6
    assert payload["queue_metrics"]["queue_length"] == 3
    assert payload["agent_metrics"]["running_agent_runs"] == 1
    assert payload["change_metrics"]["required_gate_target_types"] == ["model_route"]
    assert payload["runtime_metadata"]["step_request_protocol_version"] == "stage2-v1"
    assert payload["runtime_metadata"]["version"]["git_short_commit"] == "abc123def456"
    assert payload["readiness_metrics"]["stage7"] == 1
    assert conn.commit_called == 1
