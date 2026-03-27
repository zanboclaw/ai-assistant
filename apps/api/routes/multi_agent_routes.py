from __future__ import annotations

from fastapi import FastAPI


def register_multi_agent_routes(*, app: FastAPI, container) -> None:
    app.include_router(
        container["register_multi_agent_query_routes"](
            get_conn=container["get_conn"],
            require_actor_permission=container["require_actor_permission"],
            serialize_agent_run_row=container["serialize_agent_run_row"],
            serialize_agent_message_row=container["serialize_agent_message_row"],
            serialize_agent_artifact_row=container["serialize_agent_artifact_row"],
            fetch_task_agent_summary=container["fetch_task_agent_summary"],
            serialize_evaluator_run_row=container["serialize_evaluator_run_row"],
            serialize_workflow_proposal=container["serialize_workflow_proposal"],
            fetch_latest_evaluator_for_task=container["fetch_latest_evaluator_for_task"],
            list_workflow_proposals_rows=container["list_workflow_proposals_rows"],
            task_exists=container["task_exists"],
            get_workflow_proposal_or_404=container["get_workflow_proposal_or_404"],
            build_workflow_proposal_shadow_validation_response=container["build_workflow_proposal_shadow_validation_response"],
            build_workflow_proposal_shadow_status=container["build_workflow_proposal_shadow_status"],
            build_workflow_proposal_shadow_validation_status_with_context=container["build_workflow_proposal_shadow_validation_status_with_context"],
            get_workflow_proposal_change_request_draft_response=container["get_workflow_proposal_change_request_draft_response"],
            suggest_change_request_draft_from_workflow_proposal_with_context=container["suggest_change_request_draft_from_workflow_proposal_with_context"],
            attach_patch_artifacts_to_change_request_draft_with_context=container["attach_patch_artifacts_to_change_request_draft_with_context"],
            attach_shadow_validation_state_to_change_request_draft_with_context=container["attach_shadow_validation_state_to_change_request_draft_with_context"],
            fetch_evaluator_run_row=container["fetch_evaluator_run_row"],
            get_evaluator_run_or_404=container["get_evaluator_run_or_404"],
        )
    )
    app.include_router(
        container["register_multi_agent_demo_routes"](
            get_conn=container["get_conn"],
            require_actor_permission=container["require_actor_permission"],
            ensure_agent_tables=container["ensure_agent_tables"],
            build_task_display_user_input=container["build_task_display_user_input"],
            parse_maybe_json=container["parse_maybe_json"],
            multi_agent_protocol_version=container["MULTI_AGENT_PROTOCOL_VERSION"],
            create_agent_artifact=container["create_agent_artifact"],
            create_agent_run=container["create_agent_run"],
            create_agent_message=container["create_agent_message"],
            build_specialist_execution_request=container["build_specialist_execution_request"],
            insert_audit_log=container["insert_audit_log"],
            logger=container["logger"],
            safe_json_dumps=container["safe_json_dumps"],
            serialize_agent_artifact_row=container["serialize_agent_artifact_row"],
            build_specialist_step_partitions=container["build_specialist_step_partitions"],
            build_specialist_draft_payload=container["build_specialist_draft_payload"],
            enqueue_agent_run=container["enqueue_agent_run"],
            resolve_reviewer_decision=container["resolve_reviewer_decision"],
            build_demo_review_criteria=container["build_demo_review_criteria"],
            derive_evaluator_failure_profile=container["derive_evaluator_failure_profile"],
            build_workflow_proposal=container["build_workflow_proposal"],
            create_evaluator_run=container["create_evaluator_run"],
            serialize_workflow_proposal=container["serialize_workflow_proposal"],
        )
    )

