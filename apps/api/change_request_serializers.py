from typing import Any

from change_request_helpers import (
    change_request_requires_shadow_validation,
    normalize_change_request_acceptance_status,
    normalize_change_request_shadow_validation_status,
)
from json_utils import compute_stable_payload_hash, make_json_compatible
from serializers import parse_maybe_json


def build_shadow_validation_candidate_overlay(
    *,
    target_type: str,
    target_key: str,
    proposed_payload: dict[str, Any] | None,
    baseline_payload: dict[str, Any] | None = None,
    patch_summary: str = "",
    source: str = "",
    source_change_request_id: int | None = None,
) -> dict[str, Any]:
    normalized_target_type = str(target_type or "").strip()
    normalized_target_key = str(target_key or "").strip()
    payload = proposed_payload or {}
    if not normalized_target_type or not normalized_target_key or not isinstance(payload, dict):
        return {}
    overlay = {
        "target_type": normalized_target_type,
        "target_key": normalized_target_key,
        "proposed_payload": make_json_compatible(payload),
        "payload_hash": compute_stable_payload_hash(payload),
    }
    if baseline_payload:
        overlay["baseline_payload"] = make_json_compatible(baseline_payload)
    if patch_summary:
        overlay["patch_summary"] = patch_summary
    if source:
        overlay["source"] = source
    if source_change_request_id is not None:
        overlay["source_change_request_id"] = int(source_change_request_id)
    return overlay


def extract_shadow_validation_candidate_overlay(validation_report: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(validation_report, dict):
        return {}
    validation_payload = validation_report.get("validation")
    if isinstance(validation_payload, dict) and isinstance(validation_payload.get("candidate_overlay"), dict):
        return dict(validation_payload.get("candidate_overlay") or {})
    if isinstance(validation_report.get("candidate_overlay"), dict):
        return dict(validation_report.get("candidate_overlay") or {})
    return {}


def shadow_validation_candidate_matches(
    validation_report: dict[str, Any] | None,
    *,
    target_type: str,
    target_key: str,
    proposed_payload: dict[str, Any] | None,
) -> bool:
    candidate_overlay = extract_shadow_validation_candidate_overlay(validation_report)
    if not candidate_overlay:
        return False
    normalized_target_type = str(target_type or "").strip()
    normalized_target_key = str(target_key or "").strip()
    payload = proposed_payload or {}
    if not normalized_target_type or not normalized_target_key or not isinstance(payload, dict):
        return False
    return (
        str(candidate_overlay.get("target_type") or "").strip() == normalized_target_type
        and str(candidate_overlay.get("target_key") or "").strip() == normalized_target_key
        and str(candidate_overlay.get("payload_hash") or "").strip() == compute_stable_payload_hash(payload)
    )


def summarize_json_payload(payload: Any) -> dict[str, Any]:
    normalized = make_json_compatible(payload)
    if isinstance(normalized, dict):
        return {
            "kind": "object",
            "key_count": len(normalized),
            "keys": sorted(str(key) for key in normalized.keys())[:20],
            "hash": compute_stable_payload_hash(normalized),
        }
    if isinstance(normalized, list):
        return {
            "kind": "array",
            "item_count": len(normalized),
        }
    if normalized in (None, "", {}, []):
        return {"kind": "empty"}
    return {
        "kind": type(normalized).__name__,
        "value": normalized,
    }


def serialize_change_request_row(row: dict[str, Any]) -> dict[str, Any]:
    proposal_kind = row.get("proposal_kind") or "manual_change"
    proposed_payload = parse_maybe_json(row.get("proposed_payload")) or {}
    source_workflow_proposal_id = int(row["source_workflow_proposal_id"]) if row.get("source_workflow_proposal_id") is not None else None
    shadow_validation_status = normalize_change_request_shadow_validation_status(row.get("shadow_validation_status"))
    shadow_validation_report = parse_maybe_json(row.get("shadow_validation_report")) or {}
    acceptance_status = normalize_change_request_acceptance_status(row.get("acceptance_status"))
    acceptance_report = parse_maybe_json(row.get("acceptance_report")) or {}
    auto_rollback_change_request_id = (
        int(row["auto_rollback_change_request_id"])
        if row.get("auto_rollback_change_request_id") is not None
        else None
    )
    requires_shadow_validation = change_request_requires_shadow_validation(
        proposal_kind=proposal_kind,
        source_workflow_proposal_id=source_workflow_proposal_id,
        target_type=str(row.get("target_type") or "").strip(),
    )
    return {
        "id": int(row["id"]),
        "target_type": row["target_type"],
        "target_key": row["target_key"],
        "proposed_payload": proposed_payload,
        "proposed_payload_hash": compute_stable_payload_hash(proposed_payload),
        "rationale": row.get("rationale") or "",
        "status": row["status"],
        "requested_by_actor": row["requested_by_actor"],
        "reviewed_by_actor": row.get("reviewed_by_actor"),
        "decision_note": row.get("decision_note") or "",
        "applied_by_actor": row.get("applied_by_actor"),
        "proposal_kind": proposal_kind,
        "source_change_request_id": int(row["source_change_request_id"]) if row.get("source_change_request_id") is not None else None,
        "source_workflow_proposal_id": source_workflow_proposal_id,
        "shadow_validation_status": shadow_validation_status,
        "shadow_validation_report": shadow_validation_report,
        "shadow_validation_candidate_match": shadow_validation_candidate_matches(
            shadow_validation_report,
            target_type=row["target_type"],
            target_key=row["target_key"],
            proposed_payload=proposed_payload,
        ),
        "requires_shadow_validation": requires_shadow_validation,
        "shadow_validation_ready_to_apply": (not requires_shadow_validation) or shadow_validation_status == "completed",
        "baseline_payload": parse_maybe_json(row.get("baseline_payload")) or {},
        "payload_patch": parse_maybe_json(row.get("payload_patch")) or {},
        "patch_summary": row.get("patch_summary") or "",
        "rollback_payload": parse_maybe_json(row.get("rollback_payload")) or {},
        "rollback_ready": bool(row.get("rollback_ready")),
        "rollback_note": row.get("rollback_note") or "",
        "acceptance_configured": isinstance(proposed_payload.get("acceptance"), dict) and bool(proposed_payload.get("acceptance")),
        "acceptance_status": acceptance_status,
        "acceptance_report": acceptance_report,
        "auto_rollback_change_request_id": auto_rollback_change_request_id,
        "auto_rollback_applied": auto_rollback_change_request_id is not None,
        "can_create_rollback": (
            row.get("status") == "applied"
            and bool(row.get("rollback_ready"))
            and auto_rollback_change_request_id is None
        ),
        "created_at": row.get("created_at"),
        "acceptance_at": row.get("acceptance_at"),
        "shadow_validation_at": row.get("shadow_validation_at"),
        "auto_rollback_at": row.get("auto_rollback_at"),
        "reviewed_at": row.get("reviewed_at"),
        "applied_at": row.get("applied_at"),
    }


def serialize_change_request_list_row(row: dict[str, Any]) -> dict[str, Any]:
    serialized = serialize_change_request_row(row)
    proposed_payload = serialized.pop("proposed_payload", {})
    baseline_payload = serialized.pop("baseline_payload", {})
    rollback_payload = serialized.pop("rollback_payload", {})
    shadow_validation_report = serialized.get("shadow_validation_report", {})
    acceptance_report = serialized.pop("acceptance_report", {})
    payload_patch = serialized.pop("payload_patch", {}) or {}

    serialized["proposed_payload_summary"] = summarize_json_payload(proposed_payload)
    serialized["baseline_payload_summary"] = summarize_json_payload(baseline_payload)
    serialized["rollback_payload_summary"] = summarize_json_payload(rollback_payload)
    serialized["payload_patch_summary"] = summarize_json_payload(payload_patch)
    serialized["shadow_validation_report_summary"] = summarize_json_payload(shadow_validation_report)
    serialized["acceptance_report_summary"] = summarize_json_payload(acceptance_report)
    return serialized
