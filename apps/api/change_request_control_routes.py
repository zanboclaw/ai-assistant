from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Header, HTTPException

from schemas import ChangeRequestCreate, ChangeRequestDecision, WorkflowProposalBridgeRequest, WorkflowProposalShadowValidationRequest


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


def register_change_request_control_routes(
    *,
    get_conn: Callable[[], Any],
    require_actor_permission: Callable[[Any, str | None, str], dict[str, Any]],
    supported_change_target_types: set[str],
    create_change_request_with_audit: Callable[..., dict[str, Any]],
    create_change_request_row: Callable[..., dict[str, Any]],
    serialize_change_request_row: Callable[[dict[str, Any]], dict[str, Any]],
    insert_audit_log: Callable[[Any, str, str, int | None, Any | None], None],
    ensure_change_requests_table: Callable[[Any], None],
    get_change_request_or_404: Callable[[Any, Callable[[Any], None], int], dict[str, Any]],
    review_change_request: Callable[..., dict[str, Any]],
    update_reviewed_change_request_row: Callable[..., dict[str, Any]],
    execute_change_request_apply: Callable[..., dict[str, Any]],
    normalize_change_request_payload: Callable[[str, dict[str, Any]], dict[str, Any]],
    fetch_change_target_state_for_rollback_with_context: Callable[..., dict[str, Any] | None],
    apply_change_request_payload_with_context: Callable[[Any, str, str, dict[str, Any]], None],
    process_change_request_post_apply_with_context: Callable[..., dict[str, Any]],
    safe_json_dumps: Callable[[Any], str],
    update_applied_change_request_row: Callable[..., dict[str, Any]],
    prepare_change_request_rollback_context: Callable[..., dict[str, Any]],
    build_change_request_rollback_draft: Callable[[dict[str, Any]], dict[str, Any]],
    find_open_rollback_change_request: Callable[[Any, int, Callable[[Any], None]], dict[str, Any] | None],
    get_workflow_proposal_or_404: Callable[..., dict[str, Any]],
    serialize_evaluator_run_row: Callable[[dict[str, Any]], dict[str, Any]],
    serialize_workflow_proposal: Callable[..., dict[str, Any]],
    create_change_request_from_workflow_proposal_draft: Callable[..., dict[str, Any]],
    build_change_request_draft_from_workflow_proposal: Callable[..., dict[str, Any]],
    record_audit_event: Callable[[str, str, int | None, Any | None], None],
    launch_workflow_proposal_shadow_validation: Callable[..., dict[str, Any]],
    enforce_task_quota: Callable[..., Any],
    prepare_shadow_validation_baseline: Callable[..., Any],
    resolve_shadow_validation_candidate_overlay_with_context: Callable[..., dict[str, Any] | None],
    build_shadow_validation_runtime_overrides: Callable[..., dict[str, Any]],
    build_shadow_validation_execution_payload_with_context: Callable[..., dict[str, Any]],
    parse_optional_int: Callable[[Any], int | None],
    complete_workflow_proposal_shadow_validation: Callable[..., dict[str, Any]],
    enqueue_task: Callable[[int], Any],
    finalize_shadow_validation_response_with_context: Callable[..., dict[str, Any]],
    resolve_change_request_shadow_validation_target: Callable[..., dict[str, Any]],
    ensure_change_request_shadow_validation_eligible: Callable[..., int],
):
    router = APIRouter()

    def execute_workflow_proposal_shadow_validation(
        *,
        workflow_proposal: dict[str, Any],
        request: WorkflowProposalShadowValidationRequest,
        x_actor_name: str | None,
        source_change_request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        conn = get_conn()
        cur = conn.cursor()
        try:
            launch_result = launch_workflow_proposal_shadow_validation(
                cur,
                workflow_proposal=workflow_proposal,
                request=request,
                x_actor_name=x_actor_name,
                source_change_request=source_change_request,
                require_actor_permission_fn=require_actor_permission,
                enforce_task_quota_fn=enforce_task_quota,
                prepare_shadow_validation_baseline_fn=prepare_shadow_validation_baseline,
                resolve_shadow_validation_candidate_overlay_fn=resolve_shadow_validation_candidate_overlay_with_context,
                build_shadow_validation_runtime_overrides_fn=build_shadow_validation_runtime_overrides,
                build_shadow_validation_execution_payload_fn=build_shadow_validation_execution_payload_with_context,
                parse_optional_int_fn=parse_optional_int,
                safe_json_dumps_fn=safe_json_dumps,
                insert_audit_log_fn=insert_audit_log,
            )
            conn.commit()
        finally:
            cur.close()
            conn.close()

        shadow_context = launch_result["shadow_context"]
        shadow_task = launch_result["shadow_task"]
        return complete_workflow_proposal_shadow_validation(
            workflow_proposal=workflow_proposal,
            request=request,
            source_change_request=source_change_request,
            shadow_context=shadow_context,
            shadow_task=shadow_task,
            enqueue_task_fn=enqueue_task,
            finalize_shadow_validation_response_fn=finalize_shadow_validation_response_with_context,
        )

    @router.post("/change-requests")
    def create_change_request(
        request: ChangeRequestCreate,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        target_type = request.target_type.strip()
        target_key = request.target_key.strip()
        if target_type not in supported_change_target_types:
            raise HTTPException(status_code=400, detail=f"Unsupported change target type: {target_type}")
        if not target_key:
            raise HTTPException(status_code=400, detail="target_key is required")

        conn = get_conn()
        cur = conn.cursor()
        try:
            actor = require_actor_permission(cur, x_actor_name, "operate")
            serialized_row = create_change_request_with_audit(
                cur=cur,
                target_type=target_type,
                target_key=target_key,
                proposed_payload=request.proposed_payload,
                rationale=request.rationale,
                requested_by_actor=actor["actor_name"],
                create_change_request_row_fn=create_change_request_row,
                serialize_change_request_row_fn=serialize_change_request_row,
                insert_audit_log_fn=insert_audit_log,
            )
            conn.commit()
        finally:
            cur.close()
            conn.close()
        return serialized_row

    @router.post("/change-requests/{change_request_id}/approve")
    def approve_change_request(
        change_request_id: int,
        request: ChangeRequestDecision,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        try:
            actor = require_actor_permission(cur, x_actor_name, "admin")
            serialized_row = review_change_request(
                cur=cur,
                change_request_id=change_request_id,
                actor_name=actor["actor_name"],
                note=request.note.strip(),
                next_status="approved",
                audit_event="change_request.approve",
                get_change_request_fn=lambda current_change_request_id: get_change_request_or_404(
                    cur,
                    ensure_change_requests_table,
                    current_change_request_id,
                ),
                update_change_request_review_fn=lambda **kwargs: update_reviewed_change_request_row(
                    cur,
                    change_request_id=change_request_id,
                    **kwargs,
                ),
                serialize_change_request_row_fn=serialize_change_request_row,
                insert_audit_log_fn=insert_audit_log,
            )
            conn.commit()
            return serialized_row
        finally:
            cur.close()
            conn.close()

    @router.post("/change-requests/{change_request_id}/reject")
    def reject_change_request(
        change_request_id: int,
        request: ChangeRequestDecision,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        try:
            actor = require_actor_permission(cur, x_actor_name, "admin")
            serialized_row = review_change_request(
                cur=cur,
                change_request_id=change_request_id,
                actor_name=actor["actor_name"],
                note=request.note.strip(),
                next_status="rejected",
                audit_event="change_request.reject",
                get_change_request_fn=lambda current_change_request_id: get_change_request_or_404(
                    cur,
                    ensure_change_requests_table,
                    current_change_request_id,
                ),
                update_change_request_review_fn=lambda **kwargs: update_reviewed_change_request_row(
                    cur,
                    change_request_id=change_request_id,
                    **kwargs,
                ),
                serialize_change_request_row_fn=serialize_change_request_row,
                insert_audit_log_fn=insert_audit_log,
            )
            conn.commit()
            return serialized_row
        finally:
            cur.close()
            conn.close()

    @router.post("/change-requests/{change_request_id}/apply")
    def apply_change_request(
        change_request_id: int,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        try:
            actor = require_actor_permission(cur, x_actor_name, "admin")
            change_request = get_change_request_or_404(cur, ensure_change_requests_table, change_request_id)
            serialized_row = execute_change_request_apply(
                cur=cur,
                change_request_id=change_request_id,
                actor_name=actor["actor_name"],
                change_request=change_request,
                normalize_change_request_payload_fn=normalize_change_request_payload,
                fetch_change_target_state_for_rollback_fn=lambda **kwargs: (
                    fetch_change_target_state_for_rollback_with_context(cur, **kwargs)
                ),
                apply_change_request_payload_fn=lambda target_type, target_key, payload: (
                    apply_change_request_payload_with_context(cur, target_type, target_key, payload)
                ),
                process_change_request_post_apply_fn=lambda **kwargs: (
                    process_change_request_post_apply_with_context(cur, **kwargs)
                ),
                safe_json_dumps_fn=safe_json_dumps,
                update_change_request_fn=lambda **kwargs: update_applied_change_request_row(
                    cur,
                    change_request_id=change_request_id,
                    **kwargs,
                ),
                serialize_change_request_row_fn=serialize_change_request_row,
                insert_audit_log_fn=lambda event_type, current_actor_name, task_id, details: insert_audit_log(
                    cur,
                    event_type,
                    current_actor_name,
                    task_id,
                    details,
                ),
            )
            conn.commit()
            return serialized_row
        finally:
            cur.close()
            conn.close()

    @router.post("/change-requests/{change_request_id}/rollback")
    def create_rollback_change_request(
        change_request_id: int,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        try:
            actor = require_actor_permission(cur, x_actor_name, "operate")
            rollback_context = prepare_change_request_rollback_context(
                change_request_id=change_request_id,
                get_change_request_fn=lambda current_change_request_id: get_change_request_or_404(
                    cur,
                    ensure_change_requests_table,
                    current_change_request_id,
                ),
                build_change_request_rollback_draft_fn=build_change_request_rollback_draft,
                find_open_rollback_change_request_fn=lambda current_change_request_id: find_open_rollback_change_request(
                    cur,
                    current_change_request_id,
                    ensure_change_requests_table,
                ),
            )
            change_request = rollback_context["change_request"]
            draft = rollback_context["draft"]
            if not draft["rollback_ready"]:
                raise HTTPException(status_code=409, detail=draft["rollback_note"] or "Rollback draft is not ready")

            existing = rollback_context["existing_rollback_change_request"]
            if existing:
                return {
                    "created": False,
                    "change_request": serialize_change_request_row(existing),
                    "source_change_request": change_request,
                }

            row = create_change_request_row(
                cur,
                target_type=draft["target_type"],
                target_key=draft["target_key"],
                proposed_payload=draft["proposed_payload"],
                rationale=draft["rationale"],
                requested_by_actor=actor["actor_name"],
                proposal_kind="rollback",
                source_change_request_id=change_request_id,
                source_workflow_proposal_id=change_request.get("source_workflow_proposal_id"),
            )
            insert_audit_log(
                cur,
                "change_request.rollback_create",
                actor["actor_name"],
                None,
                {
                    "source_change_request_id": change_request_id,
                    "rollback_change_request_id": row["id"],
                    "target_type": change_request["target_type"],
                    "target_key": change_request["target_key"],
                    "patch_summary": serialize_change_request_row(row)["patch_summary"],
                },
            )
            conn.commit()
            return {
                "created": True,
                "change_request": serialize_change_request_row(row),
                "source_change_request": change_request,
            }
        finally:
            cur.close()
            conn.close()

    @router.post("/workflow-proposals/{proposal_id}/change-request-draft")
    def create_change_request_from_workflow_proposal(
        proposal_id: int,
        request: WorkflowProposalBridgeRequest,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        try:
            workflow_proposal = load_workflow_proposal_or_404(
                cur,
                proposal_id=proposal_id,
                get_workflow_proposal_or_404=get_workflow_proposal_or_404,
                serialize_evaluator_run_row=serialize_evaluator_run_row,
                serialize_workflow_proposal=serialize_workflow_proposal,
            )
            result = create_change_request_from_workflow_proposal_draft(
                cur,
                proposal_id=proposal_id,
                workflow_proposal=workflow_proposal,
                request=request,
                x_actor_name=x_actor_name,
                supported_change_target_types=supported_change_target_types,
                require_actor_permission_fn=require_actor_permission,
                build_change_request_draft_from_workflow_proposal_fn=build_change_request_draft_from_workflow_proposal,
                create_change_request_row_fn=create_change_request_row,
                serialize_change_request_row_fn=serialize_change_request_row,
                record_audit_event_fn=record_audit_event,
            )
            conn.commit()
            return result
        finally:
            cur.close()
            conn.close()

    @router.post("/workflow-proposals/{proposal_id}/shadow-validate")
    def shadow_validate_workflow_proposal(
        proposal_id: int,
        request: WorkflowProposalShadowValidationRequest,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        try:
            workflow_proposal = load_workflow_proposal_or_404(
                cur,
                proposal_id=proposal_id,
                get_workflow_proposal_or_404=get_workflow_proposal_or_404,
                serialize_evaluator_run_row=serialize_evaluator_run_row,
                serialize_workflow_proposal=serialize_workflow_proposal,
            )
        finally:
            cur.close()
            conn.close()
        return execute_workflow_proposal_shadow_validation(
            workflow_proposal=workflow_proposal,
            request=request,
            x_actor_name=x_actor_name,
        )

    @router.post("/change-requests/{change_request_id}/shadow-validate")
    def shadow_validate_change_request(
        change_request_id: int,
        request: WorkflowProposalShadowValidationRequest,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        try:
            shadow_target = resolve_change_request_shadow_validation_target(
                cur,
                change_request_id=change_request_id,
                x_actor_name=x_actor_name,
                require_actor_permission_fn=require_actor_permission,
                get_change_request_or_404_fn=get_change_request_or_404,
                ensure_change_requests_table_fn=ensure_change_requests_table,
                ensure_change_request_shadow_validation_eligible_fn=ensure_change_request_shadow_validation_eligible,
                parse_optional_int_fn=parse_optional_int,
                get_workflow_proposal_fn=lambda proposal_id: load_workflow_proposal_or_404(
                    cur,
                    proposal_id=proposal_id,
                    get_workflow_proposal_or_404=get_workflow_proposal_or_404,
                    serialize_evaluator_run_row=serialize_evaluator_run_row,
                    serialize_workflow_proposal=serialize_workflow_proposal,
                ),
            )
        finally:
            cur.close()
            conn.close()
        return execute_workflow_proposal_shadow_validation(
            workflow_proposal=shadow_target["workflow_proposal"],
            request=request,
            x_actor_name=x_actor_name,
            source_change_request=shadow_target["change_request"],
        )

    return router
