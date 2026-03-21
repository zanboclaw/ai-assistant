from typing import Any


def _fetch_count(cur, query: str, params: tuple[Any, ...] | None = None) -> int:
    cur.execute(query, params or ())
    row = cur.fetchone() or {}
    return int(row.get("count") or 0)


def fetch_stage7_overview_metrics(cur) -> dict[str, Any]:
    stage7_workflow_improvement_change_request_count = _fetch_count(
        cur,
        """
        SELECT COUNT(*) AS count
        FROM change_requests
        WHERE proposal_kind = 'workflow_improvement';
        """,
    )
    stage7_shadow_required_change_request_count = _fetch_count(
        cur,
        """
        SELECT COUNT(*) AS count
        FROM change_requests
        WHERE proposal_kind = 'workflow_improvement'
          AND target_type = 'model_route';
        """,
    )
    stage7_shadow_completed_change_request_count = _fetch_count(
        cur,
        """
        SELECT COUNT(*) AS count
        FROM change_requests
        WHERE proposal_kind = 'workflow_improvement'
          AND shadow_validation_status = 'completed';
        """,
    )
    stage7_candidate_overlay_validation_count = _fetch_count(
        cur,
        """
        SELECT COUNT(*) AS count
        FROM audit_logs
        WHERE event_type = 'workflow_proposal.shadow_validated'
          AND COALESCE(details ->> 'validation_mode', '') = 'candidate_overlay_compare';
        """,
    )
    stage7_candidate_match_change_request_count = _fetch_count(
        cur,
        """
        SELECT COUNT(*) AS count
        FROM change_requests
        WHERE proposal_kind = 'workflow_improvement'
          AND shadow_validation_status = 'completed'
          AND LOWER(COALESCE(shadow_validation_report ->> 'candidate_match', 'false')) = 'true';
        """,
    )
    stage7_patch_artifact_ready_count = _fetch_count(
        cur,
        """
        SELECT COUNT(*) AS count
        FROM change_requests
        WHERE proposal_kind != 'rollback'
          AND status = 'applied'
          AND baseline_payload IS NOT NULL
          AND payload_patch IS NOT NULL
          AND COALESCE(patch_summary, '') != '';
        """,
    )
    stage7_rollback_ready_count = _fetch_count(
        cur,
        """
        SELECT COUNT(*) AS count
        FROM change_requests
        WHERE status = 'applied'
          AND rollback_ready = TRUE
          AND rollback_payload IS NOT NULL;
        """,
    )
    stage7_rollback_change_request_count = _fetch_count(
        cur,
        """
        SELECT COUNT(*) AS count
        FROM change_requests
        WHERE proposal_kind = 'rollback';
        """,
    )
    stage7_rollback_applied_count = _fetch_count(
        cur,
        """
        SELECT COUNT(*) AS count
        FROM change_requests
        WHERE proposal_kind = 'rollback'
          AND status = 'applied';
        """,
    )
    stage7_sandbox_file_applied_count = _fetch_count(
        cur,
        """
        SELECT COUNT(*) AS count
        FROM change_requests
        WHERE target_type = 'sandbox_file'
          AND proposal_kind != 'rollback'
          AND status = 'applied';
        """,
    )
    stage7_sandbox_source_copy_applied_count = _fetch_count(
        cur,
        """
        SELECT COUNT(*) AS count
        FROM change_requests
        WHERE target_type = 'sandbox_file'
          AND proposal_kind != 'rollback'
          AND status = 'applied'
          AND proposed_payload ? 'source_copy';
        """,
    )
    stage7_sandbox_source_patch_applied_count = _fetch_count(
        cur,
        """
        SELECT COUNT(*) AS count
        FROM change_requests
        WHERE target_type = 'sandbox_file'
          AND proposal_kind != 'rollback'
          AND status = 'applied'
          AND proposed_payload ? 'patch_applied';
        """,
    )
    stage7_sandbox_acceptance_passed_count = _fetch_count(
        cur,
        """
        SELECT COUNT(*) AS count
        FROM change_requests
        WHERE target_type = 'sandbox_file'
          AND proposal_kind != 'rollback'
          AND status = 'applied'
          AND acceptance_status = 'passed';
        """,
    )
    stage7_sandbox_acceptance_failed_count = _fetch_count(
        cur,
        """
        SELECT COUNT(*) AS count
        FROM change_requests
        WHERE target_type = 'sandbox_file'
          AND proposal_kind != 'rollback'
          AND status = 'applied'
          AND acceptance_status IN ('failed', 'timed_out', 'error');
        """,
    )
    stage7_sandbox_auto_rollback_applied_count = _fetch_count(
        cur,
        """
        SELECT COUNT(*) AS count
        FROM change_requests
        WHERE target_type = 'sandbox_file'
          AND proposal_kind != 'rollback'
          AND status = 'applied'
          AND auto_rollback_change_request_id IS NOT NULL;
        """,
    )

    return {
        "stage7_workflow_improvement_change_request_count": stage7_workflow_improvement_change_request_count,
        "stage7_shadow_required_change_request_count": stage7_shadow_required_change_request_count,
        "stage7_shadow_completed_change_request_count": stage7_shadow_completed_change_request_count,
        "stage7_candidate_overlay_validation_count": stage7_candidate_overlay_validation_count,
        "stage7_candidate_match_change_request_count": stage7_candidate_match_change_request_count,
        "stage7_patch_artifact_ready_count": stage7_patch_artifact_ready_count,
        "stage7_rollback_ready_count": stage7_rollback_ready_count,
        "stage7_rollback_change_request_count": stage7_rollback_change_request_count,
        "stage7_rollback_applied_count": stage7_rollback_applied_count,
        "stage7_sandbox_file_applied_count": stage7_sandbox_file_applied_count,
        "stage7_sandbox_source_copy_applied_count": stage7_sandbox_source_copy_applied_count,
        "stage7_sandbox_source_patch_applied_count": stage7_sandbox_source_patch_applied_count,
        "stage7_sandbox_acceptance_passed_count": stage7_sandbox_acceptance_passed_count,
        "stage7_sandbox_acceptance_failed_count": stage7_sandbox_acceptance_failed_count,
        "stage7_sandbox_auto_rollback_applied_count": stage7_sandbox_auto_rollback_applied_count,
    }
