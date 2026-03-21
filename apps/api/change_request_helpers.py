import os

from fastapi import HTTPException


CHANGE_GATE_REQUIRED_TARGET_TYPES = {
    "risk_policy",
    "tool_registry",
    "model_route",
    "model_provider",
}

SHADOW_VALIDATION_RUNTIME_OVERRIDE_TARGET_TYPES = {
    "model_route",
}

DEFAULT_ENFORCED_CHANGE_TARGET_TYPES = {
    item.strip()
    for item in os.environ.get("CHANGE_GATE_ENFORCED_TARGET_TYPES", "").split(",")
    if item.strip()
}

CHANGE_REQUEST_PROPOSAL_KINDS = {
    "manual_change",
    "workflow_improvement",
    "rollback",
}

CHANGE_REQUEST_ACCEPTANCE_STATUSES = {
    "not_configured",
    "passed",
    "failed",
    "timed_out",
    "error",
}

CHANGE_REQUEST_SHADOW_VALIDATION_STATUSES = {
    "not_required",
    "required",
    "completed",
}

WORKFLOW_PROPOSAL_SHADOW_VALIDATION_REQUEST_EVENT = "workflow_proposal.shadow_validation"
WORKFLOW_PROPOSAL_SHADOW_VALIDATION_RESULT_EVENT = "workflow_proposal.shadow_validated"

CHANGE_REQUEST_SELECT_FIELDS = (
    "id, target_type, target_key, proposed_payload, rationale, status, "
    "requested_by_actor, reviewed_by_actor, decision_note, applied_by_actor, "
    "proposal_kind, source_change_request_id, source_workflow_proposal_id, "
    "shadow_validation_status, shadow_validation_report, shadow_validation_at, "
    "baseline_payload, payload_patch, patch_summary, "
    "rollback_payload, rollback_ready, rollback_note, "
    "acceptance_status, acceptance_report, acceptance_at, "
    "auto_rollback_change_request_id, auto_rollback_at, "
    "created_at, reviewed_at, applied_at"
)


def normalize_change_request_proposal_kind(proposal_kind: str | None) -> str:
    normalized = str(proposal_kind or "manual_change").strip().lower() or "manual_change"
    if normalized not in CHANGE_REQUEST_PROPOSAL_KINDS:
        raise HTTPException(status_code=400, detail=f"Unsupported proposal_kind: {proposal_kind}")
    return normalized


def normalize_change_request_shadow_validation_status(status: str | None) -> str:
    normalized = str(status or "not_required").strip().lower() or "not_required"
    if normalized not in CHANGE_REQUEST_SHADOW_VALIDATION_STATUSES:
        return "not_required"
    return normalized


def normalize_change_request_acceptance_status(status: str | None) -> str:
    normalized = str(status or "not_configured").strip().lower() or "not_configured"
    if normalized not in CHANGE_REQUEST_ACCEPTANCE_STATUSES:
        return "not_configured"
    return normalized


def change_request_requires_shadow_validation(
    *,
    proposal_kind: str | None,
    source_workflow_proposal_id: int | None,
    target_type: str = "",
) -> bool:
    return (
        normalize_change_request_proposal_kind(proposal_kind) == "workflow_improvement"
        and source_workflow_proposal_id is not None
        and str(target_type or "").strip() in SHADOW_VALIDATION_RUNTIME_OVERRIDE_TARGET_TYPES
    )
