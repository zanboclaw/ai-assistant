from __future__ import annotations

from typing import Any, Mapping


def register_all_routes(*, app, context: Mapping[str, Any]) -> None:
    ctx = context

    app.include_router(
        ctx["register_intake_task_routes"](
            ensure_skill_registry_tables=ctx["ensure_skill_registry_tables"],
            get_conn=ctx["get_conn"],
            attach_task_display_fields=ctx["attach_task_display_fields"],
            insert_audit_log=ctx["insert_audit_log"],
            enqueue_task=ctx["enqueue_task"],
            fetch_task_agent_summary=ctx["fetch_task_agent_summary"],
        )
    )

    app.include_router(
        ctx["register_task_query_routes"](
            get_conn=ctx["get_conn"],
            require_actor_permission=ctx["require_actor_permission"],
            ensure_agent_tables=ctx["ensure_agent_tables"],
            ensure_evaluator_tables=ctx["ensure_evaluator_tables"],
            ensure_trace_tables=ctx["ensure_trace_tables"],
            attach_task_display_fields=ctx["attach_task_display_fields"],
            parse_maybe_json=ctx["parse_maybe_json"],
            fetch_latest_evaluator_for_task=ctx["fetch_latest_evaluator_for_task"],
            fetch_task_agent_summary=ctx["fetch_task_agent_summary"],
        )
    )

    app.include_router(
        ctx["register_multi_agent_query_routes"](
            get_conn=ctx["get_conn"],
            require_actor_permission=ctx["require_actor_permission"],
            serialize_agent_run_row=ctx["serialize_agent_run_row"],
            serialize_agent_message_row=ctx["serialize_agent_message_row"],
            serialize_agent_artifact_row=ctx["serialize_agent_artifact_row"],
            fetch_task_agent_summary=ctx["fetch_task_agent_summary"],
            serialize_evaluator_run_row=ctx["serialize_evaluator_run_row"],
            serialize_workflow_proposal=ctx["serialize_workflow_proposal"],
            fetch_latest_evaluator_for_task=ctx["fetch_latest_evaluator_for_task"],
            list_workflow_proposals_rows=ctx["list_workflow_proposals_rows"],
            task_exists=ctx["task_exists"],
            get_workflow_proposal_or_404=ctx["get_workflow_proposal_or_404"],
            build_workflow_proposal_shadow_validation_response=ctx["build_workflow_proposal_shadow_validation_response"],
            build_workflow_proposal_shadow_status=ctx["build_workflow_proposal_shadow_status"],
            build_workflow_proposal_shadow_validation_status_with_context=ctx["build_workflow_proposal_shadow_validation_status_with_context"],
            get_workflow_proposal_change_request_draft_response=ctx["get_workflow_proposal_change_request_draft_response"],
            suggest_change_request_draft_from_workflow_proposal_with_context=ctx[
                "suggest_change_request_draft_from_workflow_proposal_with_context"
            ],
            attach_patch_artifacts_to_change_request_draft_with_context=ctx[
                "attach_patch_artifacts_to_change_request_draft_with_context"
            ],
            attach_shadow_validation_state_to_change_request_draft_with_context=ctx[
                "attach_shadow_validation_state_to_change_request_draft_with_context"
            ],
            fetch_evaluator_run_row=ctx["fetch_evaluator_run_row"],
            get_evaluator_run_or_404=ctx["get_evaluator_run_or_404"],
        )
    )

    app.include_router(
        ctx["register_task_control_routes"](
            get_conn=ctx["get_conn"],
            require_actor_permission=ctx["require_actor_permission"],
            get_task_or_404=ctx["get_task_or_404"],
            update_checkpoint_status=ctx["update_checkpoint_status"],
            insert_audit_log=ctx["insert_audit_log"],
            resolve_resume_from_step=ctx["resolve_resume_from_step"],
            reset_task_for_resume=ctx["reset_task_for_resume"],
            reset_task_for_clarification=ctx["reset_task_for_clarification"],
            enqueue_task=ctx["enqueue_task"],
            parse_maybe_json=ctx["parse_maybe_json"],
            extract_task_clarification_state=ctx["extract_task_clarification_state"],
            build_clarified_user_input=ctx["build_clarified_user_input"],
            infer_task_intent=ctx["infer_task_intent"],
            build_task_display_user_input=ctx["build_task_display_user_input"],
            infer_deliverable_spec=ctx["infer_deliverable_spec"],
            logger=ctx["logger"],
        )
    )

    app.include_router(
        ctx["register_multi_agent_demo_routes"](
            get_conn=ctx["get_conn"],
            require_actor_permission=ctx["require_actor_permission"],
            ensure_agent_tables=ctx["ensure_agent_tables"],
            build_task_display_user_input=ctx["build_task_display_user_input"],
            parse_maybe_json=ctx["parse_maybe_json"],
            multi_agent_protocol_version=ctx["MULTI_AGENT_PROTOCOL_VERSION"],
            create_agent_artifact=ctx["create_agent_artifact"],
            create_agent_run=ctx["create_agent_run"],
            create_agent_message=ctx["create_agent_message"],
            build_specialist_execution_request=ctx["build_specialist_execution_request"],
            insert_audit_log=ctx["insert_audit_log"],
            logger=ctx["logger"],
            safe_json_dumps=ctx["safe_json_dumps"],
            serialize_agent_artifact_row=ctx["serialize_agent_artifact_row"],
            build_specialist_step_partitions=ctx["build_specialist_step_partitions"],
            build_specialist_draft_payload=ctx["build_specialist_draft_payload"],
            enqueue_agent_run=ctx["enqueue_agent_run"],
            resolve_reviewer_decision=ctx["resolve_reviewer_decision"],
            build_demo_review_criteria=ctx["build_demo_review_criteria"],
            derive_evaluator_failure_profile=ctx["derive_evaluator_failure_profile"],
            build_workflow_proposal=ctx["build_workflow_proposal"],
            create_evaluator_run=ctx["create_evaluator_run"],
            serialize_workflow_proposal=ctx["serialize_workflow_proposal"],
        )
    )

    app.include_router(
        ctx["register_change_request_query_routes"](
            get_conn=lambda: ctx["get_conn"](),
            require_actor_permission=lambda cur, actor_name, permission: ctx["require_actor_permission"](cur, actor_name, permission),
            ensure_change_requests_table=lambda cur: ctx["ensure_change_requests_table"](cur),
            normalize_change_request_proposal_kind=ctx["normalize_change_request_proposal_kind"],
            change_request_select_fields=ctx["CHANGE_REQUEST_SELECT_FIELDS"],
            serialize_change_request_row=lambda row: ctx["serialize_change_request_row"](row),
            serialize_change_request_list_row=lambda row: ctx["serialize_change_request_list_row"](row),
            get_change_request_or_404=lambda cur, ensure_fn, change_request_id: (
                ctx["get_change_request_or_404"](cur, ensure_fn, change_request_id)
            ),
            collect_change_request_shadow_validation_context=lambda cur, change_request: (
                ctx["collect_change_request_shadow_validation_context"](cur, change_request)
            ),
            parse_optional_int=ctx["parse_optional_int"],
            build_workflow_proposal_shadow_validation_status_with_context=lambda cur, proposal_id: (
                ctx["build_workflow_proposal_shadow_validation_status_with_context"](cur, proposal_id)
            ),
            fetch_latest_workflow_proposal_shadow_validation_with_context=lambda cur, proposal_id: (
                ctx["fetch_latest_workflow_proposal_shadow_validation_with_context"](cur, proposal_id)
            ),
            fetch_task_run_brief_with_context=lambda cur, task_id: ctx["fetch_task_run_brief_with_context"](cur, task_id),
            build_change_request_shadow_validation_response=lambda change_request, context_payload: (
                ctx["build_change_request_shadow_validation_response"](change_request, context_payload)
            ),
            prepare_change_request_rollback_context=lambda cur, change_request: (
                ctx["prepare_change_request_rollback_context"](cur, change_request)
            ),
            build_change_request_rollback_draft=lambda change_request, rollback_context: (
                ctx["build_change_request_rollback_draft"](change_request, rollback_context)
            ),
            find_open_rollback_change_request=lambda cur, source_change_request_id: (
                ctx["find_open_rollback_change_request"](cur, source_change_request_id)
            ),
            attach_patch_artifacts_to_change_request_draft_with_context=lambda cur, draft: (
                ctx["attach_patch_artifacts_to_change_request_draft_with_context"](cur, draft)
            ),
            attach_shadow_validation_state_to_change_request_draft_with_context=lambda cur, draft: (
                ctx["attach_shadow_validation_state_to_change_request_draft_with_context"](cur, draft)
            ),
        )
    )

    app.include_router(
        ctx["register_change_request_control_routes"](
            get_conn=ctx["get_conn"],
            require_actor_permission=ctx["require_actor_permission"],
            supported_change_target_types=ctx["SUPPORTED_CHANGE_TARGET_TYPES"],
            create_change_request_with_audit=ctx["create_change_request_with_audit"],
            create_change_request_row=ctx["create_change_request_row"],
            serialize_change_request_row=ctx["serialize_change_request_row"],
            insert_audit_log=ctx["insert_audit_log"],
            ensure_change_requests_table=ctx["ensure_change_requests_table"],
            get_change_request_or_404=ctx["get_change_request_or_404"],
            review_change_request=ctx["review_change_request"],
            update_reviewed_change_request_row=ctx["_update_reviewed_change_request_row"],
            execute_change_request_apply=ctx["execute_change_request_apply"],
            normalize_change_request_payload=ctx["normalize_change_request_payload"],
            fetch_change_target_state_for_rollback_with_context=ctx["fetch_change_target_state_for_rollback_with_context"],
            apply_change_request_payload_with_context=ctx["apply_change_request_payload_with_context"],
            process_change_request_post_apply_with_context=ctx["process_change_request_post_apply_with_context"],
            safe_json_dumps=ctx["safe_json_dumps"],
            update_applied_change_request_row=ctx["_update_applied_change_request_row"],
            prepare_change_request_rollback_context=ctx["prepare_change_request_rollback_context"],
            build_change_request_rollback_draft=ctx["build_change_request_rollback_draft"],
            find_open_rollback_change_request=ctx["find_open_rollback_change_request"],
            get_workflow_proposal_or_404=ctx["get_workflow_proposal_or_404"],
            serialize_evaluator_run_row=ctx["serialize_evaluator_run_row"],
            serialize_workflow_proposal=ctx["serialize_workflow_proposal"],
            create_change_request_from_workflow_proposal_draft=ctx["create_change_request_from_workflow_proposal_draft"],
            build_change_request_draft_from_workflow_proposal=ctx["build_change_request_draft_from_workflow_proposal"],
            record_audit_event=ctx["record_audit_event"],
            launch_workflow_proposal_shadow_validation=ctx["launch_workflow_proposal_shadow_validation"],
            enforce_task_quota=ctx["enforce_task_quota"],
            prepare_shadow_validation_baseline=ctx["prepare_shadow_validation_baseline"],
            resolve_shadow_validation_candidate_overlay_with_context=ctx["resolve_shadow_validation_candidate_overlay_with_context"],
            build_shadow_validation_runtime_overrides=ctx["build_shadow_validation_runtime_overrides"],
            build_shadow_validation_execution_payload_with_context=ctx["build_shadow_validation_execution_payload_with_context"],
            parse_optional_int=ctx["parse_optional_int"],
            complete_workflow_proposal_shadow_validation=ctx["complete_workflow_proposal_shadow_validation"],
            enqueue_task=ctx["enqueue_task"],
            finalize_shadow_validation_response_with_context=ctx["finalize_shadow_validation_response_with_context"],
            resolve_change_request_shadow_validation_target=ctx["resolve_change_request_shadow_validation_target"],
            ensure_change_request_shadow_validation_eligible=ctx["ensure_change_request_shadow_validation_eligible"],
        )
    )

    app.include_router(
        ctx["register_session_routes"](
            get_conn=lambda: ctx["get_conn"](),
            require_actor_permission=lambda cur, actor_name, permission: ctx["require_actor_permission"](cur, actor_name, permission),
            record_audit_event=lambda event_type, actor, task_id=None, details=None: (
                ctx["record_audit_event"](event_type, actor, task_id, details)
            ),
            insert_audit_log=lambda cur, event_type, actor, task_id=None, details=None: (
                ctx["insert_audit_log"](cur, event_type, actor, task_id, details)
            ),
            attach_task_display_fields=lambda row: ctx["attach_task_display_fields"](row),
            serialize_session_row=lambda row: ctx["serialize_session_row"](row),
            serialize_session_memory_row=ctx["serialize_session_memory_row"],
            serialize_session_state_row=ctx["serialize_session_state_row"],
            serialize_session_review_row=ctx["serialize_session_review_row"],
            compute_session_health=ctx["compute_session_health"],
            load_session_health_context=lambda cur, session_id: ctx["load_session_health_context"](cur, session_id),
            refresh_session_review_context=ctx["refresh_session_review_context"],
            build_session_review=ctx["build_session_review"],
            insert_session_review_row=ctx["insert_session_review_row"],
            safe_json_dumps=ctx["safe_json_dumps"],
            compute_session_state_from_rows=ctx["compute_session_state_from_rows"],
            upsert_computed_session_state=ctx["upsert_computed_session_state"],
            refresh_session_reviews=ctx["refresh_session_reviews"],
            refresh_session_task_summary_memories=ctx["refresh_session_task_summary_memories"],
            merge_memory_into_session_state=ctx["merge_memory_into_session_state"],
            logger=ctx["logger"],
        )
    )

    app.include_router(
        ctx["register_monitor_routes"](
            get_conn=ctx["get_conn"],
            require_actor_permission=ctx["require_actor_permission"],
            ensure_risk_policies_table=ctx["ensure_risk_policies_table"],
            ensure_access_actors_table=ctx["ensure_access_actors_table"],
            ensure_access_quotas_table=ctx["ensure_access_quotas_table"],
            ensure_tool_registry_table=ctx["ensure_tool_registry_table"],
            ensure_model_providers_table=ctx["ensure_model_providers_table"],
            ensure_model_routes_table=ctx["ensure_model_routes_table"],
            ensure_change_requests_table=ctx["ensure_change_requests_table"],
            ensure_agent_tables=ctx["ensure_agent_tables"],
            fetch_monitor_overview_snapshot=ctx["fetch_monitor_overview_snapshot"],
            build_task_display_user_input=ctx["build_task_display_user_input"],
            extract_task_clarification_state=ctx["extract_task_clarification_state"],
            parse_maybe_json=ctx["parse_maybe_json"],
            serialize_session_review_row=ctx["serialize_session_review_row"],
            serialize_agent_run_row=ctx["serialize_agent_run_row"],
            serialize_evaluator_run_row=ctx["serialize_evaluator_run_row"],
            list_workflow_proposals_rows=ctx["list_workflow_proposals_rows"],
            fetch_stage56_overview_metrics=ctx["fetch_stage56_overview_metrics"],
            fetch_task_agent_summary=ctx["fetch_task_agent_summary"],
            mainline_specialist_execution_modes=list(ctx["MAINLINE_SPECIALIST_EXECUTION_MODES"]),
            mainline_specialist_tool_profiles=list(ctx["MAINLINE_SPECIALIST_TOOL_PROFILES"]),
            fetch_stage7_overview_metrics=ctx["fetch_stage7_overview_metrics"],
            get_redis_monitor_stats=ctx["get_redis_monitor_stats"],
            compute_stage_readiness_metrics=ctx["compute_stage_readiness_metrics"],
            default_enforced_change_target_types=ctx["DEFAULT_ENFORCED_CHANGE_TARGET_TYPES"],
            change_gate_required_target_types=ctx["CHANGE_GATE_REQUIRED_TARGET_TYPES"],
            step_request_protocol_version=ctx["STEP_REQUEST_PROTOCOL_VERSION"],
            multi_agent_protocol_version=ctx["MULTI_AGENT_PROTOCOL_VERSION"],
        )
    )

    app.include_router(
        ctx["register_governance_routes"](
            get_conn=lambda: ctx["get_conn"](),
            require_actor_permission=lambda cur, actor_name, permission: ctx["require_actor_permission"](cur, actor_name, permission),
            seed_default_risk_policies=lambda cur: ctx["seed_default_risk_policies"](cur),
            deserialize_policy_row=ctx["deserialize_policy_row"],
            seed_default_tool_registry=lambda cur: ctx["seed_default_tool_registry"](cur),
            serialize_tool_registry_row=ctx["serialize_tool_registry_row"],
            seed_default_model_providers=lambda cur: ctx["seed_default_model_providers"](cur),
            seed_default_model_routes=lambda cur: ctx["seed_default_model_routes"](cur),
            serialize_model_route_row=ctx["serialize_model_route_row"],
            serialize_model_provider_row=ctx["serialize_model_provider_row"],
            seed_default_access_actors=lambda cur: ctx["seed_default_access_actors"](cur),
            seed_default_access_quotas=lambda cur: ctx["seed_default_access_quotas"](cur),
            serialize_access_actor_row=ctx["serialize_access_actor_row"],
            serialize_access_quota_row=ctx["serialize_access_quota_row"],
            parse_maybe_json=ctx["parse_maybe_json"],
            validate_policy_value=ctx["validate_policy_value"],
            update_risk_policy_entry=ctx["update_risk_policy_entry"],
            update_tool_registry_entry=ctx["update_tool_registry_entry"],
            update_model_route_entry=ctx["update_model_route_entry"],
            upsert_model_provider_entry=ctx["upsert_model_provider_entry"],
            upsert_access_actor=ctx["upsert_access_actor"],
            upsert_access_quota=ctx["upsert_access_quota"],
            upsert_default_access_quota=ctx["upsert_default_access_quota"],
            insert_audit_log=ctx["insert_audit_log"],
            enforce_change_gate_for_direct_update=ctx["enforce_change_gate_for_direct_update"],
            ensure_audit_logs_table=ctx["ensure_audit_logs_table"],
            access_role_permissions=ctx["ACCESS_ROLE_PERMISSIONS"],
            step_request_protocol_version=ctx["STEP_REQUEST_PROTOCOL_VERSION"],
            step_execution_request_fields=ctx["STEP_EXECUTION_REQUEST_FIELDS"],
            enriched_step_execution_request_extra_fields=ctx["ENRICHED_STEP_EXECUTION_REQUEST_EXTRA_FIELDS"],
            multi_agent_protocol_version=ctx["MULTI_AGENT_PROTOCOL_VERSION"],
            auto_stage5_postrun_enabled=ctx["AUTO_STAGE5_POSTRUN_ENABLED"],
            logger=ctx["logger"],
        )
    )

    app.include_router(
        ctx["register_skill_routes"](
            get_conn=ctx["get_conn"],
            require_actor_permission=ctx["require_actor_permission"],
            ensure_skill_registry_tables=ctx["ensure_skill_registry_tables"],
            read_skill_package_from_source=ctx["_read_skill_package_from_source"],
            serialize_skill_row=ctx["serialize_skill_row"],
            serialize_skill_version_row=ctx["serialize_skill_version_row"],
            insert_audit_log=ctx["insert_audit_log"],
            json_wrapper=ctx["Json"],
        )
    )
