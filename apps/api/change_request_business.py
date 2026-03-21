import time
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException


def build_change_request_draft_from_workflow_proposal(
    *,
    workflow_proposal: dict[str, Any],
    target_type: str = "",
    target_key: str = "",
    proposed_payload: dict[str, Any] | None = None,
    rationale: str = "",
    supported_target_types: list[str] | None = None,
) -> dict[str, Any]:
    normalized_target_type = target_type.strip()
    normalized_target_key = target_key.strip()
    proposal_id = int(workflow_proposal.get("id") or 0)
    base_rationale = rationale.strip() or str(workflow_proposal.get("rationale") or "").strip()
    metadata_suffix = (
        f"workflow proposal #{proposal_id} "
        f"action={workflow_proposal.get('action_key') or 'unknown'} "
        f"priority={workflow_proposal.get('priority') or 'unknown'} "
        f"task_id={workflow_proposal.get('task_run_id') or ''}"
    ).strip()
    composed_rationale = metadata_suffix if not base_rationale else f"{base_rationale}\n\n来源：{metadata_suffix}"
    payload = proposed_payload or {}
    return {
        "bridge_ready": bool(normalized_target_type and normalized_target_key and isinstance(payload, dict)),
        "target_type": normalized_target_type,
        "target_key": normalized_target_key,
        "proposed_payload": payload,
        "baseline_payload": {},
        "payload_patch": {},
        "patch_summary": "",
        "rationale": composed_rationale,
        "proposal_kind": "workflow_improvement",
        "source_workflow_proposal_id": proposal_id or None,
        "source_workflow_proposal": workflow_proposal,
        "supported_target_types": sorted(supported_target_types or []),
    }


def build_shadow_validation_result(
    *,
    workflow_proposal: dict[str, Any],
    baseline_task_id: int,
    shadow_task: dict[str, Any],
    shadow_evaluator: dict[str, Any],
    candidate_overlay: dict[str, Any] | None = None,
    runtime_overrides: dict[str, Any] | None = None,
    validation_mode: str = "task_replay_compare",
    make_json_compatible_fn=None,
) -> dict[str, Any]:
    baseline_score = int(workflow_proposal.get("score") or 0)
    shadow_score = int((shadow_evaluator or {}).get("score") or 0)
    baseline_decision = str(workflow_proposal.get("decision") or "")
    shadow_decision = str((shadow_evaluator or {}).get("decision") or "")
    if shadow_score > baseline_score:
        validation_result = "improved"
    elif shadow_score < baseline_score:
        validation_result = "regressed"
    elif shadow_decision != baseline_decision:
        validation_result = "changed"
    else:
        validation_result = "matched"

    normalize = make_json_compatible_fn or (lambda value: value)
    return {
        "proposal_id": int(workflow_proposal.get("id") or 0),
        "baseline_task_id": baseline_task_id,
        "baseline_evaluator_run_id": int(workflow_proposal.get("evaluator_run_id") or 0) or None,
        "baseline_score": baseline_score,
        "baseline_decision": baseline_decision,
        "shadow_task_id": int((shadow_task or {}).get("id") or 0) or None,
        "shadow_task_status": str((shadow_task or {}).get("status") or ""),
        "shadow_evaluator_run_id": int((shadow_evaluator or {}).get("id") or 0) or None,
        "shadow_score": shadow_score,
        "shadow_decision": shadow_decision,
        "score_delta": shadow_score - baseline_score,
        "validation_result": validation_result,
        "validation_mode": validation_mode,
        "candidate_overlay": normalize(candidate_overlay or {}),
        "shadow_runtime_overrides": normalize(runtime_overrides or {}),
    }


def annotate_shadow_validation_report_for_change_request(
    validation_report: dict[str, Any] | None,
    *,
    target_type: str,
    target_key: str,
    proposed_payload: dict[str, Any] | None,
    make_json_compatible_fn,
    shadow_validation_candidate_matches_fn,
    compute_stable_payload_hash_fn,
) -> dict[str, Any]:
    if not isinstance(validation_report, dict):
        return {}
    report = make_json_compatible_fn(dict(validation_report))
    report["candidate_match"] = shadow_validation_candidate_matches_fn(
        report,
        target_type=target_type,
        target_key=target_key,
        proposed_payload=proposed_payload,
    )
    report["current_change_request"] = {
        "target_type": str(target_type or "").strip(),
        "target_key": str(target_key or "").strip(),
        "proposed_payload_hash": compute_stable_payload_hash_fn(proposed_payload or {}),
    }
    return report


def build_change_request_rollback_draft(change_request: dict[str, Any]) -> dict[str, Any]:
    rollback_payload = change_request.get("rollback_payload") or {}
    rollback_note = str(change_request.get("rollback_note") or "").strip()
    rollback_ready = bool(change_request.get("rollback_ready")) and isinstance(rollback_payload, dict) and bool(rollback_payload)
    base_rationale = (
        f"Rollback change request #{change_request['id']} "
        f"({change_request['target_type']}/{change_request['target_key']})"
    )
    if rollback_note:
        base_rationale = f"{base_rationale}\n\n原因：{rollback_note}"
    return {
        "rollback_ready": rollback_ready,
        "target_type": change_request["target_type"],
        "target_key": change_request["target_key"],
        "proposal_kind": "rollback",
        "source_change_request_id": int(change_request["id"]),
        "source_workflow_proposal_id": change_request.get("source_workflow_proposal_id"),
        "proposed_payload": rollback_payload,
        "rationale": base_rationale,
        "rollback_note": rollback_note,
        "baseline_payload": {},
        "payload_patch": {},
        "patch_summary": "",
        "shadow_validation_status": "not_required",
        "shadow_validation_report": {},
        "requires_shadow_validation": False,
        "shadow_validation_ready_to_apply": True,
        "shadow_validation_at": None,
        "source_change_request": change_request,
    }


def build_change_request_shadow_validation_response(
    *,
    change_request: dict[str, Any],
    proposal_shadow_validation: dict[str, Any],
    latest_matching_validation: dict[str, Any] | None,
    latest_proposal_validation: dict[str, Any] | None,
    latest_shadow_task: dict[str, Any] | None,
    parse_optional_int_fn,
) -> dict[str, Any]:
    synced_audit_id = parse_optional_int_fn((change_request.get("shadow_validation_report") or {}).get("audit_log_id"))
    latest_validation_audit_id = parse_optional_int_fn((latest_matching_validation or {}).get("audit_log_id"))
    return {
        "change_request": {
            "id": change_request["id"],
            "status": change_request["status"],
            "proposal_kind": change_request.get("proposal_kind") or "manual_change",
            "source_workflow_proposal_id": change_request.get("source_workflow_proposal_id"),
            "requires_shadow_validation": bool(change_request.get("requires_shadow_validation")),
            "shadow_validation_status": change_request.get("shadow_validation_status") or "not_required",
            "shadow_validation_ready_to_apply": bool(change_request.get("shadow_validation_ready_to_apply")),
            "shadow_validation_at": change_request.get("shadow_validation_at"),
            "shadow_validation_report": change_request.get("shadow_validation_report") or {},
        },
        "proposal_shadow_validation_status": proposal_shadow_validation.get("status"),
        "proposal_shadow_validation_supported": bool(proposal_shadow_validation.get("supported")),
        "latest_validation_synced": (
            synced_audit_id is not None
            and latest_validation_audit_id is not None
            and synced_audit_id == latest_validation_audit_id
        ),
        "latest_request": proposal_shadow_validation.get("latest_request"),
        "latest_validation": latest_matching_validation,
        "latest_proposal_validation": latest_proposal_validation,
        "latest_shadow_task": latest_shadow_task,
        "history_count": proposal_shadow_validation.get("history_count", 0),
        "request_count": proposal_shadow_validation.get("request_count", 0),
        "validation_count": proposal_shadow_validation.get("validation_count", 0),
        "history": proposal_shadow_validation.get("history") or [],
    }


def prepare_change_request_rollback_context(
    *,
    change_request_id: int,
    get_change_request_fn,
    build_change_request_rollback_draft_fn,
    find_open_rollback_change_request_fn,
) -> dict[str, Any]:
    change_request = get_change_request_fn(change_request_id)
    if change_request["status"] != "applied":
        raise HTTPException(status_code=400, detail=f"Change request is not applied: {change_request['status']}")

    draft = build_change_request_rollback_draft_fn(change_request)
    existing = find_open_rollback_change_request_fn(change_request_id)
    return {
        "change_request": change_request,
        "draft": draft,
        "existing_rollback_change_request": existing,
    }


def collect_change_request_shadow_validation_context(
    *,
    change_request: dict[str, Any],
    history_limit: int,
    parse_optional_int_fn,
    build_workflow_proposal_shadow_validation_status_fn,
    fetch_latest_workflow_proposal_shadow_validation_fn,
    fetch_task_run_brief_fn,
) -> dict[str, Any]:
    proposal_id = parse_optional_int_fn(change_request.get("source_workflow_proposal_id"))
    requires_shadow_validation = bool(change_request.get("requires_shadow_validation"))
    latest_matching_validation = None
    latest_proposal_validation = None
    latest_shadow_task = None

    if proposal_id is not None and proposal_id > 0:
        proposal_shadow_validation = build_workflow_proposal_shadow_validation_status_fn(
            proposal_id,
            history_limit=history_limit,
            supported=requires_shadow_validation,
        )
        latest_matching_validation = fetch_latest_workflow_proposal_shadow_validation_fn(
            proposal_id,
            target_type=str(change_request.get("target_type") or "").strip(),
            target_key=str(change_request.get("target_key") or "").strip(),
            proposed_payload=change_request.get("proposed_payload") or {},
        )
        latest_proposal_validation = proposal_shadow_validation.get("latest_validation")
        if latest_matching_validation:
            latest_shadow_task = fetch_task_run_brief_fn(
                parse_optional_int_fn((latest_matching_validation.get("validation") or {}).get("shadow_task_id"))
                or parse_optional_int_fn(latest_matching_validation.get("shadow_task_id"))
            )
        else:
            latest_shadow_task = proposal_shadow_validation.get("latest_shadow_task")
    else:
        proposal_shadow_validation = {
            "proposal_id": proposal_id,
            "supported": False,
            "status": "not_required" if not requires_shadow_validation else "not_started",
            "history_count": 0,
            "request_count": 0,
            "validation_count": 0,
            "latest_request": None,
            "latest_validation": None,
            "latest_shadow_task": None,
            "history": [],
        }

    return {
        "proposal_shadow_validation": proposal_shadow_validation,
        "latest_matching_validation": latest_matching_validation,
        "latest_proposal_validation": latest_proposal_validation,
        "latest_shadow_task": latest_shadow_task,
    }


def build_change_request_shadow_validation_state(
    *,
    proposal_kind: str | None,
    source_workflow_proposal_id: int | None,
    target_type: str = "",
    target_key: str = "",
    proposed_payload: dict[str, Any] | None = None,
    normalize_change_request_proposal_kind_fn,
    change_request_requires_shadow_validation_fn,
    fetch_latest_workflow_proposal_shadow_validation_fn,
    annotate_shadow_validation_report_for_change_request_fn,
) -> dict[str, Any]:
    normalized_proposal_kind = normalize_change_request_proposal_kind_fn(proposal_kind)
    if not change_request_requires_shadow_validation_fn(
        proposal_kind=normalized_proposal_kind,
        source_workflow_proposal_id=source_workflow_proposal_id,
        target_type=target_type,
    ):
        return {
            "shadow_validation_status": "not_required",
            "shadow_validation_report": {},
            "shadow_validation_at": None,
        }

    matching_validation = fetch_latest_workflow_proposal_shadow_validation_fn(
        int(source_workflow_proposal_id or 0),
        target_type=target_type,
        target_key=target_key,
        proposed_payload=proposed_payload,
    )
    if matching_validation:
        shadow_validation_report = annotate_shadow_validation_report_for_change_request_fn(
            matching_validation,
            target_type=target_type,
            target_key=target_key,
            proposed_payload=proposed_payload,
        )
        shadow_validation_at = shadow_validation_report.pop("validated_at_timestamp", None)
        return {
            "shadow_validation_status": "completed",
            "shadow_validation_report": shadow_validation_report,
            "shadow_validation_at": shadow_validation_at,
        }

    latest_validation = fetch_latest_workflow_proposal_shadow_validation_fn(
        int(source_workflow_proposal_id or 0),
    )
    if not latest_validation:
        return {
            "shadow_validation_status": "required",
            "shadow_validation_report": {},
            "shadow_validation_at": None,
        }
    shadow_validation_report = annotate_shadow_validation_report_for_change_request_fn(
        latest_validation,
        target_type=target_type,
        target_key=target_key,
        proposed_payload=proposed_payload,
    )
    return {
        "shadow_validation_status": "required",
        "shadow_validation_report": shadow_validation_report,
        "shadow_validation_at": None,
    }


def build_change_request_create_payload(
    *,
    target_type: str,
    target_key: str,
    proposed_payload: dict[str, Any],
    rationale: str,
    requested_by_actor: str,
    proposal_kind: str,
    source_change_request_id: int | None,
    source_workflow_proposal_id: int | None,
    normalize_change_request_payload_fn,
    build_change_request_patch_artifacts_fn,
    build_change_request_shadow_validation_state_fn,
) -> dict[str, Any]:
    normalized_proposed_payload = normalize_change_request_payload_fn(target_type, proposed_payload)
    patch_artifacts = build_change_request_patch_artifacts_fn(
        target_type=target_type,
        target_key=target_key,
        proposed_payload=normalized_proposed_payload,
    )
    shadow_validation_state = build_change_request_shadow_validation_state_fn(
        proposal_kind=proposal_kind,
        source_workflow_proposal_id=source_workflow_proposal_id,
        target_type=target_type,
        target_key=target_key,
        proposed_payload=normalized_proposed_payload,
    )
    return {
        "target_type": target_type,
        "target_key": target_key,
        "proposed_payload": normalized_proposed_payload,
        "rationale": rationale.strip(),
        "requested_by_actor": requested_by_actor,
        "proposal_kind": proposal_kind,
        "source_change_request_id": source_change_request_id,
        "source_workflow_proposal_id": source_workflow_proposal_id,
        "shadow_validation_status": shadow_validation_state["shadow_validation_status"],
        "shadow_validation_report": shadow_validation_state["shadow_validation_report"],
        "shadow_validation_at": shadow_validation_state["shadow_validation_at"],
        "baseline_payload": patch_artifacts["baseline_payload"],
        "payload_patch": patch_artifacts["payload_patch"],
        "patch_summary": patch_artifacts["patch_summary"],
    }


def create_change_request_with_audit(
    *,
    cur,
    target_type: str,
    target_key: str,
    proposed_payload: dict[str, Any],
    rationale: str,
    requested_by_actor: str,
    create_change_request_row_fn,
    serialize_change_request_row_fn,
    insert_audit_log_fn,
) -> dict[str, Any]:
    row = create_change_request_row_fn(
        cur,
        target_type=target_type,
        target_key=target_key,
        proposed_payload=proposed_payload,
        rationale=rationale,
        requested_by_actor=requested_by_actor,
    )
    serialized_row = serialize_change_request_row_fn(row)
    insert_audit_log_fn(
        cur,
        "change_request.create",
        requested_by_actor,
        None,
        {
            "change_request_id": row["id"],
            "target_type": target_type,
            "target_key": target_key,
            "proposal_kind": serialized_row["proposal_kind"],
            "patch_summary": serialized_row["patch_summary"],
        },
    )
    return serialized_row


def review_change_request(
    *,
    cur,
    change_request_id: int,
    actor_name: str,
    note: str,
    next_status: str,
    audit_event: str,
    get_change_request_fn,
    update_change_request_review_fn,
    serialize_change_request_row_fn,
    insert_audit_log_fn,
) -> dict[str, Any]:
    change_request = get_change_request_fn(change_request_id)
    if change_request["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Change request is not pending: {change_request['status']}")

    row = update_change_request_review_fn(
        actor_name=actor_name,
        note=note,
        next_status=next_status,
    )
    insert_audit_log_fn(
        cur,
        audit_event,
        actor_name,
        None,
        {"change_request_id": change_request_id},
    )
    return serialize_change_request_row_fn(row)


def build_change_request_patch_artifacts(
    *,
    target_type: str,
    target_key: str,
    proposed_payload: dict[str, Any],
    baseline_payload: dict[str, Any] | None = None,
    normalize_change_request_payload_fn,
    fetch_change_target_state_for_rollback_fn,
    compute_change_payload_patch_fn,
) -> dict[str, Any]:
    normalized_payload = normalize_change_request_payload_fn(target_type, proposed_payload or {})
    baseline = baseline_payload
    if baseline is None:
        baseline = fetch_change_target_state_for_rollback_fn(target_type=target_type, target_key=target_key)
    baseline = baseline or {}
    payload_patch, patch_summary = compute_change_payload_patch_fn(baseline, normalized_payload)
    if not patch_summary:
        patch_summary = "no field changes" if baseline else "baseline unavailable"
    return {
        "baseline_payload": baseline,
        "payload_patch": payload_patch,
        "patch_summary": patch_summary,
    }


def attach_patch_artifacts_to_change_request_draft(
    *,
    draft: dict[str, Any],
    normalize_change_request_payload_fn,
    build_change_request_patch_artifacts_fn,
) -> dict[str, Any]:
    target_type = str(draft.get("target_type") or "").strip()
    target_key = str(draft.get("target_key") or "").strip()
    proposed_payload = draft.get("proposed_payload") or {}
    if not target_type or not target_key or not isinstance(proposed_payload, dict):
        return draft
    normalized_proposed_payload = normalize_change_request_payload_fn(target_type, proposed_payload)
    patch_artifacts = build_change_request_patch_artifacts_fn(
        target_type=target_type,
        target_key=target_key,
        proposed_payload=normalized_proposed_payload,
    )
    draft["proposed_payload"] = normalized_proposed_payload
    draft["baseline_payload"] = patch_artifacts["baseline_payload"]
    draft["payload_patch"] = patch_artifacts["payload_patch"]
    draft["patch_summary"] = patch_artifacts["patch_summary"]
    return draft


def attach_shadow_validation_state_to_change_request_draft(
    *,
    draft: dict[str, Any],
    normalize_change_request_payload_fn,
    change_request_requires_shadow_validation_fn,
    build_change_request_shadow_validation_state_fn,
) -> dict[str, Any]:
    proposal_kind = str(draft.get("proposal_kind") or "manual_change").strip() or "manual_change"
    source_workflow_proposal_id = int(draft.get("source_workflow_proposal_id") or 0) or None
    target_type = str(draft.get("target_type") or "").strip()
    target_key = str(draft.get("target_key") or "").strip()
    proposed_payload = normalize_change_request_payload_fn(target_type, draft.get("proposed_payload") or {})
    requires_shadow_validation = change_request_requires_shadow_validation_fn(
        proposal_kind=proposal_kind,
        source_workflow_proposal_id=source_workflow_proposal_id,
        target_type=target_type,
    )
    shadow_validation_state = build_change_request_shadow_validation_state_fn(
        proposal_kind=proposal_kind,
        source_workflow_proposal_id=source_workflow_proposal_id,
        target_type=target_type,
        target_key=target_key,
        proposed_payload=proposed_payload,
    )
    draft["proposed_payload"] = proposed_payload
    draft["shadow_validation_status"] = shadow_validation_state["shadow_validation_status"]
    draft["shadow_validation_report"] = shadow_validation_state["shadow_validation_report"]
    draft["requires_shadow_validation"] = requires_shadow_validation
    draft["shadow_validation_ready_to_apply"] = (
        (not requires_shadow_validation)
        or shadow_validation_state["shadow_validation_status"] == "completed"
    )
    draft["shadow_validation_at"] = shadow_validation_state["shadow_validation_at"]
    return draft


def apply_change_request_payload(
    *,
    target_type: str,
    target_key: str,
    payload: dict[str, Any],
    normalize_sandbox_file_payload_fn,
    apply_sandbox_file_payload_fn,
    apply_risk_policy_fn,
    apply_tool_registry_fn,
    apply_model_route_fn,
    apply_model_provider_fn,
    apply_access_quota_fn,
    apply_access_actor_fn,
) -> None:
    if target_type == "sandbox_file":
        normalized_payload = normalize_sandbox_file_payload_fn(payload)
        apply_sandbox_file_payload_fn(target_key, normalized_payload)
        return
    if target_type == "risk_policy":
        apply_risk_policy_fn(target_key, payload)
        return
    if target_type == "tool_registry":
        apply_tool_registry_fn(target_key, payload)
        return
    if target_type == "model_route":
        apply_model_route_fn(target_key, payload)
        return
    if target_type == "model_provider":
        apply_model_provider_fn(target_key, payload)
        return
    if target_type == "access_quota":
        apply_access_quota_fn(target_key, payload)
        return
    if target_type == "access_actor":
        apply_access_actor_fn(target_key, payload)
        return
    raise HTTPException(status_code=400, detail=f"Unsupported change target type: {target_type}")


def suggest_change_request_draft_from_workflow_proposal(
    *,
    workflow_proposal: dict[str, Any],
    supported_change_target_types: list[str],
    fetch_planner_route_fn,
    serialize_model_route_row_fn,
    build_change_request_draft_from_workflow_proposal_fn,
) -> dict[str, Any]:
    action_key = str(workflow_proposal.get("action_key") or "")
    if action_key != "expand_specialist_scope":
        return build_change_request_draft_from_workflow_proposal_fn(
            workflow_proposal=workflow_proposal,
            supported_target_types=supported_change_target_types,
        )

    row = fetch_planner_route_fn()
    if not row:
        return build_change_request_draft_from_workflow_proposal_fn(
            workflow_proposal=workflow_proposal,
            supported_target_types=supported_change_target_types,
        )

    current_route = serialize_model_route_row_fn(row)
    suggested_payload = {
        "provider": current_route["provider"],
        "model_name": current_route["model_name"],
        "temperature": current_route["temperature"],
        "max_tokens": max(int(current_route["max_tokens"]), 1800),
        "enabled": True,
        "description": (
            (current_route.get("description") or "").strip() + " | support readonly specialist expansion"
        ).strip(" |"),
    }
    draft = build_change_request_draft_from_workflow_proposal_fn(
        workflow_proposal=workflow_proposal,
        target_type="model_route",
        target_key="planner",
        proposed_payload=suggested_payload,
        supported_target_types=supported_change_target_types,
    )
    draft["suggestion_source"] = "auto_action_mapping"
    draft["suggested_from"] = {
        "target_type": "model_route",
        "target_key": "planner",
        "current_route": current_route,
    }
    return draft


def resolve_shadow_validation_candidate_overlay(
    *,
    workflow_proposal: dict[str, Any],
    request,
    source_change_request: dict[str, Any] | None = None,
    build_shadow_validation_candidate_overlay_fn,
    parse_optional_int_fn,
    build_change_request_patch_artifacts_fn,
    suggest_change_request_draft_from_workflow_proposal_fn,
    attach_patch_artifacts_to_change_request_draft_fn,
) -> dict[str, Any]:
    if source_change_request:
        return build_shadow_validation_candidate_overlay_fn(
            target_type=str(source_change_request.get("target_type") or "").strip(),
            target_key=str(source_change_request.get("target_key") or "").strip(),
            proposed_payload=source_change_request.get("proposed_payload") or {},
            baseline_payload=source_change_request.get("baseline_payload") or {},
            patch_summary=str(source_change_request.get("patch_summary") or "").strip(),
            source="change_request",
            source_change_request_id=parse_optional_int_fn(source_change_request.get("id")),
        )

    explicit_target_type = str(request.candidate_target_type or "").strip()
    explicit_target_key = str(request.candidate_target_key or "").strip()
    explicit_payload = request.candidate_payload or {}
    if explicit_target_type and explicit_target_key and isinstance(explicit_payload, dict):
        patch_artifacts = build_change_request_patch_artifacts_fn(
            target_type=explicit_target_type,
            target_key=explicit_target_key,
            proposed_payload=explicit_payload,
        )
        return build_shadow_validation_candidate_overlay_fn(
            target_type=explicit_target_type,
            target_key=explicit_target_key,
            proposed_payload=explicit_payload,
            baseline_payload=patch_artifacts["baseline_payload"],
            patch_summary=patch_artifacts["patch_summary"],
            source="request_payload",
        )

    if not bool(request.use_suggested_candidate):
        return {}

    draft = suggest_change_request_draft_from_workflow_proposal_fn(workflow_proposal=workflow_proposal)
    draft = attach_patch_artifacts_to_change_request_draft_fn(draft=draft)
    if not draft.get("bridge_ready"):
        return {}
    return build_shadow_validation_candidate_overlay_fn(
        target_type=str(draft.get("target_type") or "").strip(),
        target_key=str(draft.get("target_key") or "").strip(),
        proposed_payload=draft.get("proposed_payload") or {},
        baseline_payload=draft.get("baseline_payload") or {},
        patch_summary=str(draft.get("patch_summary") or "").strip(),
        source=str(draft.get("suggestion_source") or "workflow_proposal_suggestion"),
    )


def wait_for_shadow_validation_completion(
    *,
    workflow_proposal: dict[str, Any],
    baseline_task_id: int,
    shadow_task_id: int,
    actor_name: str,
    timeout_seconds: int,
    poll_interval_seconds: float,
    candidate_overlay: dict[str, Any] | None = None,
    runtime_overrides: dict[str, Any] | None = None,
    validation_mode: str = "task_replay_compare",
    terminal_statuses: set[str] | None = None,
    fetch_shadow_task_and_evaluator_fn,
    build_shadow_validation_result_fn,
    record_shadow_validation_result_fn,
) -> dict[str, Any] | None:
    deadline = time.time() + timeout_seconds
    accepted_terminal_statuses = terminal_statuses or {"completed", "failed"}

    while time.time() <= deadline:
        shadow_task, shadow_evaluator = fetch_shadow_task_and_evaluator_fn(shadow_task_id)
        shadow_status = str((shadow_task or {}).get("status") or "")

        if shadow_task and shadow_evaluator and shadow_status in accepted_terminal_statuses:
            validation = build_shadow_validation_result_fn(
                workflow_proposal=workflow_proposal,
                baseline_task_id=baseline_task_id,
                shadow_task=shadow_task,
                shadow_evaluator=shadow_evaluator,
                candidate_overlay=candidate_overlay,
                runtime_overrides=runtime_overrides,
                validation_mode=validation_mode,
            )
            record_shadow_validation_result_fn(
                workflow_proposal=workflow_proposal,
                baseline_task_id=baseline_task_id,
                actor_name=actor_name,
                validation=validation,
            )
            return {
                "shadow_task": shadow_task,
                "shadow_evaluator": shadow_evaluator,
                "validation": validation,
            }

        time.sleep(poll_interval_seconds)

    return None


def process_change_request_post_apply(
    *,
    change_request_id: int,
    change_request: dict[str, Any],
    normalized_proposed_payload: dict[str, Any],
    rollback_payload: dict[str, Any] | None,
    rollback_ready: bool,
    rollback_note: str,
    actor_name: str,
    execute_sandbox_file_acceptance_fn,
    make_json_compatible_fn,
    insert_audit_log_fn,
    create_and_apply_automatic_rollback_change_request_fn,
) -> dict[str, Any]:
    acceptance_status = "not_configured"
    acceptance_report: dict[str, Any] = {}
    acceptance_at: datetime | None = None
    auto_rollback_change_request_id: int | None = None
    auto_rollback_at: datetime | None = None

    if change_request["target_type"] == "sandbox_file":
        acceptance_status, acceptance_report, acceptance_finished_at = execute_sandbox_file_acceptance_fn(
            change_request_id=change_request_id,
            target_key=change_request["target_key"],
            normalized_payload=normalized_proposed_payload,
        )
        if acceptance_status != "not_configured":
            acceptance_at = acceptance_finished_at
            acceptance_report = make_json_compatible_fn(acceptance_report)
            insert_audit_log_fn(
                "change_request.acceptance",
                actor_name,
                None,
                {
                    "change_request_id": change_request_id,
                    "target_type": change_request["target_type"],
                    "target_key": change_request["target_key"],
                    "acceptance_status": acceptance_status,
                    "passed": acceptance_status == "passed",
                    "script_path": acceptance_report.get("script_path"),
                    "exit_code": acceptance_report.get("exit_code"),
                    "timed_out": acceptance_report.get("timed_out"),
                    "duration_ms": acceptance_report.get("duration_ms"),
                },
            )
            if acceptance_status != "passed" and rollback_ready:
                rollback_reason = (
                    "Automatic rollback after sandbox_file acceptance "
                    f"{acceptance_status} for change request #{change_request_id}"
                )
                source_change_request = {
                    **change_request,
                    "proposed_payload": normalized_proposed_payload,
                    "rollback_payload": rollback_payload,
                    "rollback_ready": rollback_ready,
                    "rollback_note": rollback_note,
                }
                auto_rollback_change_request = create_and_apply_automatic_rollback_change_request_fn(
                    source_change_request=source_change_request,
                    actor_name=actor_name,
                    reason=rollback_reason,
                )
                auto_rollback_change_request_id = int(auto_rollback_change_request["id"])
                auto_rollback_at = datetime.now(timezone.utc)
            elif acceptance_status != "passed":
                insert_audit_log_fn(
                    "change_request.auto_rollback_skipped",
                    actor_name,
                    None,
                    {
                        "change_request_id": change_request_id,
                        "target_type": change_request["target_type"],
                        "target_key": change_request["target_key"],
                        "acceptance_status": acceptance_status,
                        "reason": "rollback payload unavailable",
                    },
                )

    if acceptance_status != "not_configured":
        acceptance_report = {
            **acceptance_report,
            "auto_rollback_triggered": auto_rollback_change_request_id is not None,
        }
        if auto_rollback_change_request_id is not None:
            acceptance_report["auto_rollback_change_request_id"] = auto_rollback_change_request_id

    return {
        "acceptance_status": acceptance_status,
        "acceptance_report": acceptance_report,
        "acceptance_at": acceptance_at,
        "auto_rollback_change_request_id": auto_rollback_change_request_id,
        "auto_rollback_at": auto_rollback_at,
    }


def execute_change_request_apply(
    *,
    cur,
    change_request_id: int,
    actor_name: str,
    change_request: dict[str, Any],
    normalize_change_request_payload_fn,
    fetch_change_target_state_for_rollback_fn,
    apply_change_request_payload_fn,
    process_change_request_post_apply_fn,
    safe_json_dumps_fn,
    update_change_request_fn,
    serialize_change_request_row_fn,
    insert_audit_log_fn,
) -> dict[str, Any]:
    if change_request["status"] != "approved":
        raise HTTPException(status_code=400, detail=f"Change request is not approved: {change_request['status']}")
    if change_request.get("requires_shadow_validation") and not change_request.get("shadow_validation_ready_to_apply"):
        proposal_id = change_request.get("source_workflow_proposal_id")
        raise HTTPException(
            status_code=409,
            detail=(
                "workflow_improvement change requests require completed proposal-scoped shadow validation before apply. "
                f"Run POST /workflow-proposals/{proposal_id}/shadow-validate first."
            ),
        )

    normalized_proposed_payload = normalize_change_request_payload_fn(
        change_request["target_type"],
        change_request["proposed_payload"] or {},
    )
    rollback_payload = fetch_change_target_state_for_rollback_fn(
        target_type=change_request["target_type"],
        target_key=change_request["target_key"],
    )
    rollback_ready = isinstance(rollback_payload, dict) and bool(rollback_payload)
    rollback_note = (
        "Captured pre-change baseline for rollback."
        if rollback_ready
        else "No baseline target state found before apply; rollback draft requires manual recovery."
    )
    apply_change_request_payload_fn(
        change_request["target_type"],
        change_request["target_key"],
        normalized_proposed_payload,
    )
    post_apply_result = process_change_request_post_apply_fn(
        change_request_id=change_request_id,
        change_request=change_request,
        normalized_proposed_payload=normalized_proposed_payload,
        rollback_payload=rollback_payload,
        rollback_ready=rollback_ready,
        rollback_note=rollback_note,
        actor_name=actor_name,
    )
    acceptance_status = post_apply_result["acceptance_status"]
    acceptance_report = post_apply_result["acceptance_report"]
    acceptance_at = post_apply_result["acceptance_at"]
    auto_rollback_change_request_id = post_apply_result["auto_rollback_change_request_id"]
    auto_rollback_at = post_apply_result["auto_rollback_at"]

    row = update_change_request_fn(
        actor_name=actor_name,
        rollback_payload=rollback_payload,
        rollback_ready=rollback_ready,
        rollback_note=rollback_note,
        acceptance_status=acceptance_status,
        acceptance_report=safe_json_dumps_fn(acceptance_report) if acceptance_report else None,
        acceptance_at=acceptance_at,
        auto_rollback_change_request_id=auto_rollback_change_request_id,
        auto_rollback_at=auto_rollback_at,
    )
    serialized_row = serialize_change_request_row_fn(row)
    insert_audit_log_fn(
        "change_request.apply",
        actor_name,
        None,
        {
            "change_request_id": change_request_id,
            "target_type": change_request["target_type"],
            "target_key": change_request["target_key"],
            "proposal_kind": change_request.get("proposal_kind") or "manual_change",
            "patch_summary": serialized_row["patch_summary"],
            "rollback_ready": rollback_ready,
            "acceptance_status": acceptance_status,
            "auto_rollback_applied": auto_rollback_change_request_id is not None,
            "auto_rollback_change_request_id": auto_rollback_change_request_id,
        },
    )
    return serialized_row


def build_shadow_validation_execution_payload(
    *,
    workflow_proposal: dict[str, Any],
    baseline_task: dict[str, Any],
    request,
    actor: dict[str, Any],
    quota_snapshot: dict[str, Any],
    candidate_overlay: dict[str, Any] | None,
    runtime_overrides: dict[str, Any] | None,
    shadow_task: dict[str, Any],
    parse_optional_int_fn,
    make_json_compatible_fn,
) -> dict[str, Any]:
    proposal_id = int(workflow_proposal.get("id") or 0)
    baseline_task_id = int(workflow_proposal.get("task_run_id") or 0)
    validation_mode = str(((runtime_overrides or {}).get("shadow_validation") or {}).get("validation_mode") or "task_replay_compare")
    source_change_request_id = parse_optional_int_fn(
        ((runtime_overrides or {}).get("shadow_validation") or {}).get("source_change_request_id")
    )

    task_create_details = {
        "session_id": shadow_task.get("session_id"),
        "role": actor["role"],
        "quota": quota_snapshot,
        "source": "workflow_proposal.shadow_validation",
        "baseline_task_id": baseline_task_id,
        "proposal_id": proposal_id,
        "validation_mode": validation_mode,
        "candidate_overlay": make_json_compatible_fn(candidate_overlay),
        "source_change_request_id": source_change_request_id,
    }
    validation_request = {
        "proposal_id": proposal_id,
        "action_key": str(workflow_proposal.get("action_key") or ""),
        "baseline_task_id": baseline_task_id,
        "baseline_evaluator_run_id": int(workflow_proposal.get("evaluator_run_id") or 0) or None,
        "baseline_score": int(workflow_proposal.get("score") or 0),
        "baseline_decision": str(workflow_proposal.get("decision") or ""),
        "shadow_task_id": int(shadow_task["id"]),
        "shadow_user_input": str(shadow_task.get("user_input") or str(baseline_task.get("user_input") or "").strip()),
        "validation_mode": validation_mode,
        "candidate_overlay": make_json_compatible_fn(candidate_overlay),
        "runtime_overrides": make_json_compatible_fn(runtime_overrides),
        "source_change_request_id": source_change_request_id,
        "note": str(getattr(request, "note", "") or "").strip(),
    }
    return {
        "task_create_details": task_create_details,
        "validation_request": validation_request,
    }


def finalize_shadow_validation_response(
    *,
    workflow_proposal: dict[str, Any],
    baseline_task: dict[str, Any],
    shadow_task: dict[str, Any],
    validation_request: dict[str, Any],
    candidate_overlay: dict[str, Any] | None,
    validation_mode: str,
    source_change_request: dict[str, Any] | None,
    await_completion: bool,
    actor_name: str,
    timeout_seconds: int,
    poll_interval_seconds: float,
    runtime_overrides: dict[str, Any] | None,
    wait_for_shadow_validation_completion_fn,
    start_shadow_validation_completion_worker_fn,
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "completed": False,
        "workflow_proposal": workflow_proposal,
        "baseline_task": baseline_task,
        "shadow_task": shadow_task,
        "validation_request": validation_request,
        "candidate_overlay": candidate_overlay or {},
        "validation_mode": validation_mode,
    }
    if source_change_request:
        response["change_request"] = source_change_request

    if await_completion:
        completed = wait_for_shadow_validation_completion_fn(
            workflow_proposal=workflow_proposal,
            baseline_task_id=int(workflow_proposal.get("task_run_id") or 0),
            shadow_task_id=int(shadow_task["id"]),
            actor_name=actor_name,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            candidate_overlay=candidate_overlay,
            runtime_overrides=runtime_overrides,
            validation_mode=validation_mode,
        )
        if completed:
            response["completed"] = True
            response["shadow_task"] = completed["shadow_task"]
            response["shadow_evaluator"] = completed["shadow_evaluator"]
            response["validation"] = completed["validation"]
    else:
        start_shadow_validation_completion_worker_fn(
            workflow_proposal=workflow_proposal,
            baseline_task_id=int(workflow_proposal.get("task_run_id") or 0),
            shadow_task_id=int(shadow_task["id"]),
            actor_name=actor_name,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            candidate_overlay=candidate_overlay,
            runtime_overrides=runtime_overrides,
            validation_mode=validation_mode,
        )
        response["tracking_mode"] = "async_background_wait"

    return response


def prepare_shadow_validation_baseline(
    *,
    baseline_task: dict[str, Any] | None,
    request,
) -> dict[str, Any]:
    if not baseline_task:
        raise HTTPException(status_code=404, detail="Baseline task not found")
    if str(baseline_task.get("status") or "") not in {"completed", "failed"}:
        raise HTTPException(status_code=400, detail="Baseline task must be terminal before shadow validation")

    shadow_user_input = (getattr(request, "shadow_user_input", "") or "").strip() or str(
        baseline_task.get("user_input") or ""
    ).strip()
    if not shadow_user_input:
        raise HTTPException(status_code=400, detail="shadow_user_input is empty")
    return {
        "baseline_task": baseline_task,
        "shadow_user_input": shadow_user_input,
    }
