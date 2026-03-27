from __future__ import annotations

from fastapi import FastAPI


def register_workflow_routes(*, app: FastAPI, container) -> None:
    app.include_router(
        container["register_change_request_query_routes"](
            get_conn=lambda: container["get_conn"](),
            require_actor_permission=lambda cur, actor_name, permission: container["require_actor_permission"](cur, actor_name, permission),
            ensure_change_requests_table=lambda cur: container["ensure_change_requests_table"](cur),
            normalize_change_request_proposal_kind=container["normalize_change_request_proposal_kind"],
            change_request_select_fields=container["CHANGE_REQUEST_SELECT_FIELDS"],
            serialize_change_request_row=lambda row: container["serialize_change_request_row"](row),
            serialize_change_request_list_row=lambda row: container["serialize_change_request_list_row"](row),
            get_change_request_or_404=lambda cur, ensure_change_requests_table, change_request_id: container["get_change_request_or_404"](
                cur,
                ensure_change_requests_table,
                change_request_id,
            ),
            collect_change_request_shadow_validation_context=container["collect_change_request_shadow_validation_context"],
            parse_optional_int=container["parse_optional_int"],
            build_workflow_proposal_shadow_validation_status_with_context=container["build_workflow_proposal_shadow_validation_status_with_context"],
            fetch_latest_workflow_proposal_shadow_validation_with_context=container["fetch_latest_workflow_proposal_shadow_validation_with_context"],
            fetch_task_run_brief_with_context=container["fetch_task_run_brief_with_context"],
            build_change_request_shadow_validation_response=container["build_change_request_shadow_validation_response"],
            prepare_change_request_rollback_context=container["prepare_change_request_rollback_context"],
            build_change_request_rollback_draft=container["build_change_request_rollback_draft"],
            find_open_rollback_change_request=container["find_open_rollback_change_request"],
            attach_patch_artifacts_to_change_request_draft_with_context=container["attach_patch_artifacts_to_change_request_draft_with_context"],
            attach_shadow_validation_state_to_change_request_draft_with_context=container["attach_shadow_validation_state_to_change_request_draft_with_context"],
        )
    )
    app.include_router(
        container["register_change_request_control_routes"](
            get_conn=container["get_conn"],
            require_actor_permission=container["require_actor_permission"],
            supported_change_target_types=container["SUPPORTED_CHANGE_TARGET_TYPES"],
            create_change_request_with_audit=container["create_change_request_with_audit"],
            create_change_request_row=container["create_change_request_row"],
            serialize_change_request_row=container["serialize_change_request_row"],
            insert_audit_log=container["insert_audit_log"],
            ensure_change_requests_table=container["ensure_change_requests_table"],
            get_change_request_or_404=container["get_change_request_or_404"],
            review_change_request=container["review_change_request"],
            update_reviewed_change_request_row=container["_update_reviewed_change_request_row"],
            execute_change_request_apply=container["execute_change_request_apply"],
            normalize_change_request_payload=container["normalize_change_request_payload"],
            fetch_change_target_state_for_rollback_with_context=container["fetch_change_target_state_for_rollback_with_context"],
            apply_change_request_payload_with_context=container["apply_change_request_payload_with_context"],
            process_change_request_post_apply_with_context=container["process_change_request_post_apply_with_context"],
            safe_json_dumps=container["safe_json_dumps"],
            update_applied_change_request_row=container["_update_applied_change_request_row"],
            prepare_change_request_rollback_context=container["prepare_change_request_rollback_context"],
            build_change_request_rollback_draft=container["build_change_request_rollback_draft"],
            find_open_rollback_change_request=container["find_open_rollback_change_request"],
            get_workflow_proposal_or_404=container["get_workflow_proposal_or_404"],
            serialize_evaluator_run_row=container["serialize_evaluator_run_row"],
            serialize_workflow_proposal=container["serialize_workflow_proposal"],
            create_change_request_from_workflow_proposal_draft=container["create_change_request_from_workflow_proposal_draft"],
            build_change_request_draft_from_workflow_proposal=container["build_change_request_draft_from_workflow_proposal"],
            record_audit_event=container["record_audit_event"],
            launch_workflow_proposal_shadow_validation=container["launch_workflow_proposal_shadow_validation"],
            enforce_task_quota=container["enforce_task_quota"],
            prepare_shadow_validation_baseline=container["prepare_shadow_validation_baseline"],
            resolve_shadow_validation_candidate_overlay_with_context=container["resolve_shadow_validation_candidate_overlay_with_context"],
            build_shadow_validation_runtime_overrides=container["build_shadow_validation_runtime_overrides"],
            build_shadow_validation_execution_payload_with_context=container["build_shadow_validation_execution_payload_with_context"],
            parse_optional_int=container["parse_optional_int"],
            complete_workflow_proposal_shadow_validation=container["complete_workflow_proposal_shadow_validation"],
            enqueue_task=container["enqueue_task"],
            finalize_shadow_validation_response_with_context=container["finalize_shadow_validation_response_with_context"],
            resolve_change_request_shadow_validation_target=container["resolve_change_request_shadow_validation_target"],
            ensure_change_request_shadow_validation_eligible=container["ensure_change_request_shadow_validation_eligible"],
        )
    )
