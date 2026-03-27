from __future__ import annotations

from fastapi import FastAPI


def register_monitor_routes(*, app: FastAPI, container) -> None:
    app.include_router(
        container["register_monitor_routes"](
            get_conn=container["get_conn"],
            require_actor_permission=container["require_actor_permission"],
            ensure_risk_policies_table=container["ensure_risk_policies_table"],
            ensure_access_actors_table=container["ensure_access_actors_table"],
            ensure_access_quotas_table=container["ensure_access_quotas_table"],
            ensure_tool_registry_table=container["ensure_tool_registry_table"],
            ensure_model_providers_table=container["ensure_model_providers_table"],
            ensure_model_routes_table=container["ensure_model_routes_table"],
            ensure_change_requests_table=container["ensure_change_requests_table"],
            ensure_agent_tables=container["ensure_agent_tables"],
            fetch_monitor_overview_snapshot=container["fetch_monitor_overview_snapshot"],
            build_task_display_user_input=container["build_task_display_user_input"],
            extract_task_clarification_state=container["extract_task_clarification_state"],
            parse_maybe_json=container["parse_maybe_json"],
            serialize_session_review_row=container["serialize_session_review_row"],
            serialize_agent_run_row=container["serialize_agent_run_row"],
            serialize_evaluator_run_row=container["serialize_evaluator_run_row"],
            list_workflow_proposals_rows=container["list_workflow_proposals_rows"],
            fetch_stage56_overview_metrics=container["fetch_stage56_overview_metrics"],
            fetch_task_agent_summary=container["fetch_task_agent_summary"],
            mainline_specialist_execution_modes=list(container["MAINLINE_SPECIALIST_EXECUTION_MODES"]),
            mainline_specialist_tool_profiles=list(container["MAINLINE_SPECIALIST_TOOL_PROFILES"]),
            fetch_stage7_overview_metrics=container["fetch_stage7_overview_metrics"],
            get_redis_monitor_stats=container["get_redis_monitor_stats"],
            compute_stage_readiness_metrics=container["compute_stage_readiness_metrics"],
            default_enforced_change_target_types=container["DEFAULT_ENFORCED_CHANGE_TARGET_TYPES"],
            change_gate_required_target_types=container["CHANGE_GATE_REQUIRED_TARGET_TYPES"],
            step_request_protocol_version=container["STEP_REQUEST_PROTOCOL_VERSION"],
            multi_agent_protocol_version=container["MULTI_AGENT_PROTOCOL_VERSION"],
            get_runtime_version_metadata=container["get_runtime_version_metadata"],
        )
    )
