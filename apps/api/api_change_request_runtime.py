from __future__ import annotations

from typing import Any, Callable


def create_change_request_row(
    cur,
    *,
    ensure_change_requests_table_fn: Callable[[Any], None],
    normalize_change_request_proposal_kind_fn: Callable[[str | None], str],
    build_change_request_create_payload_fn: Callable[..., dict[str, Any]],
    normalize_change_request_payload_fn: Callable[[str, dict[str, Any] | None], dict[str, Any]],
    build_change_request_patch_artifacts_with_context_fn: Callable[..., dict[str, Any]],
    build_change_request_shadow_validation_state_with_context_fn: Callable[..., dict[str, Any]],
    insert_change_request_row_fn: Callable[..., dict[str, Any]],
    safe_json_dumps_fn: Callable[[Any], str],
    target_type: str,
    target_key: str,
    proposed_payload: dict[str, Any],
    rationale: str,
    requested_by_actor: str,
    proposal_kind: str = "manual_change",
    source_change_request_id: int | None = None,
    source_workflow_proposal_id: int | None = None,
) -> dict[str, Any]:
    ensure_change_requests_table_fn(cur)
    normalized_proposal_kind = normalize_change_request_proposal_kind_fn(proposal_kind)
    change_request_payload = build_change_request_create_payload_fn(
        target_type=target_type,
        target_key=target_key,
        proposed_payload=proposed_payload,
        rationale=rationale,
        requested_by_actor=requested_by_actor,
        proposal_kind=normalized_proposal_kind,
        source_change_request_id=source_change_request_id,
        source_workflow_proposal_id=source_workflow_proposal_id,
        normalize_change_request_payload_fn=normalize_change_request_payload_fn,
        build_change_request_patch_artifacts_fn=lambda **kwargs: (
            build_change_request_patch_artifacts_with_context_fn(cur, **kwargs)
        ),
        build_change_request_shadow_validation_state_fn=lambda **kwargs: (
            build_change_request_shadow_validation_state_with_context_fn(cur, **kwargs)
        ),
    )
    return insert_change_request_row_fn(
        cur,
        change_request_payload=change_request_payload,
        safe_json_dumps_fn=safe_json_dumps_fn,
    )


def fetch_change_target_state_for_rollback_with_context(
    cur,
    *,
    fetch_change_target_state_for_rollback_fn: Callable[..., dict[str, Any] | None],
    fetch_sandbox_file_state_fn: Callable[[str], dict[str, Any]],
    seed_default_risk_policies_fn: Callable[[Any], None],
    deserialize_policy_row_fn: Callable[[dict[str, Any]], dict[str, Any]],
    seed_default_tool_registry_fn: Callable[[Any], None],
    serialize_tool_registry_row_fn: Callable[[dict[str, Any]], dict[str, Any]],
    seed_default_model_providers_fn: Callable[[Any], None],
    seed_default_model_routes_fn: Callable[[Any], None],
    serialize_model_route_row_fn: Callable[[dict[str, Any]], dict[str, Any]],
    serialize_model_provider_row_fn: Callable[[dict[str, Any]], dict[str, Any]],
    seed_default_access_quotas_fn: Callable[[Any], None],
    serialize_access_quota_row_fn: Callable[[dict[str, Any]], dict[str, Any]],
    seed_default_access_actors_fn: Callable[[Any], None],
    serialize_access_actor_row_fn: Callable[[dict[str, Any]], dict[str, Any]],
    target_type: str,
    target_key: str,
) -> dict[str, Any] | None:
    return fetch_change_target_state_for_rollback_fn(
        cur,
        target_type=target_type,
        target_key=target_key,
        fetch_sandbox_file_state_fn=fetch_sandbox_file_state_fn,
        seed_default_risk_policies_fn=seed_default_risk_policies_fn,
        deserialize_policy_row_fn=deserialize_policy_row_fn,
        seed_default_tool_registry_fn=seed_default_tool_registry_fn,
        serialize_tool_registry_row_fn=serialize_tool_registry_row_fn,
        seed_default_model_providers_fn=seed_default_model_providers_fn,
        seed_default_model_routes_fn=seed_default_model_routes_fn,
        serialize_model_route_row_fn=serialize_model_route_row_fn,
        serialize_model_provider_row_fn=serialize_model_provider_row_fn,
        seed_default_access_quotas_fn=seed_default_access_quotas_fn,
        serialize_access_quota_row_fn=serialize_access_quota_row_fn,
        seed_default_access_actors_fn=seed_default_access_actors_fn,
        serialize_access_actor_row_fn=serialize_access_actor_row_fn,
    )


def build_change_request_patch_artifacts_with_context(
    cur,
    *,
    build_change_request_patch_artifacts_fn: Callable[..., dict[str, Any]],
    normalize_change_request_payload_fn: Callable[[str, dict[str, Any] | None], dict[str, Any]],
    fetch_change_target_state_for_rollback_with_context_fn: Callable[..., dict[str, Any] | None],
    compute_change_payload_patch_fn: Callable[..., dict[str, Any]],
    target_type: str,
    target_key: str,
    proposed_payload: dict[str, Any],
    baseline_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_change_request_patch_artifacts_fn(
        target_type=target_type,
        target_key=target_key,
        proposed_payload=proposed_payload,
        baseline_payload=baseline_payload,
        normalize_change_request_payload_fn=normalize_change_request_payload_fn,
        fetch_change_target_state_for_rollback_fn=lambda **kwargs: (
            fetch_change_target_state_for_rollback_with_context_fn(cur, **kwargs)
        ),
        compute_change_payload_patch_fn=compute_change_payload_patch_fn,
    )


def attach_patch_artifacts_to_change_request_draft_with_context(
    cur,
    draft: dict[str, Any],
    *,
    attach_patch_artifacts_to_change_request_draft_fn: Callable[..., dict[str, Any]],
    normalize_change_request_payload_fn: Callable[[str, dict[str, Any] | None], dict[str, Any]],
    build_change_request_patch_artifacts_with_context_fn: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    return attach_patch_artifacts_to_change_request_draft_fn(
        draft=draft,
        normalize_change_request_payload_fn=normalize_change_request_payload_fn,
        build_change_request_patch_artifacts_fn=lambda **kwargs: (
            build_change_request_patch_artifacts_with_context_fn(cur, **kwargs)
        ),
    )


def attach_shadow_validation_state_to_change_request_draft_with_context(
    cur,
    draft: dict[str, Any],
    *,
    attach_shadow_validation_state_to_change_request_draft_fn: Callable[..., dict[str, Any]],
    normalize_change_request_payload_fn: Callable[[str, dict[str, Any] | None], dict[str, Any]],
    change_request_requires_shadow_validation_fn: Callable[[str | None], bool],
    build_change_request_shadow_validation_state_with_context_fn: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    return attach_shadow_validation_state_to_change_request_draft_fn(
        draft=draft,
        normalize_change_request_payload_fn=normalize_change_request_payload_fn,
        change_request_requires_shadow_validation_fn=change_request_requires_shadow_validation_fn,
        build_change_request_shadow_validation_state_fn=lambda **kwargs: (
            build_change_request_shadow_validation_state_with_context_fn(cur, **kwargs)
        ),
    )


def suggest_change_request_draft_from_workflow_proposal_with_context(
    cur,
    workflow_proposal: dict[str, Any],
    *,
    suggest_change_request_draft_from_workflow_proposal_fn: Callable[..., dict[str, Any]],
    supported_change_target_types: list[str],
    fetch_planner_route_fn: Callable[[], dict[str, Any] | None],
    serialize_model_route_row_fn: Callable[[dict[str, Any]], dict[str, Any]],
    build_change_request_draft_from_workflow_proposal_fn: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    return suggest_change_request_draft_from_workflow_proposal_fn(
        workflow_proposal=workflow_proposal,
        supported_change_target_types=supported_change_target_types,
        fetch_planner_route_fn=lambda: fetch_planner_route_fn(cur),
        serialize_model_route_row_fn=serialize_model_route_row_fn,
        build_change_request_draft_from_workflow_proposal_fn=build_change_request_draft_from_workflow_proposal_fn,
    )


def resolve_shadow_validation_candidate_overlay_with_context(
    cur,
    *,
    resolve_shadow_validation_candidate_overlay_fn: Callable[..., dict[str, Any]],
    build_shadow_validation_candidate_overlay_fn: Callable[..., dict[str, Any]],
    parse_optional_int_fn: Callable[[Any], int | None],
    build_change_request_patch_artifacts_with_context_fn: Callable[..., dict[str, Any]],
    suggest_change_request_draft_from_workflow_proposal_with_context_fn: Callable[..., dict[str, Any]],
    attach_patch_artifacts_to_change_request_draft_with_context_fn: Callable[..., dict[str, Any]],
    workflow_proposal: dict[str, Any],
    request,
    source_change_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return resolve_shadow_validation_candidate_overlay_fn(
        workflow_proposal=workflow_proposal,
        request=request,
        source_change_request=source_change_request,
        build_shadow_validation_candidate_overlay_fn=build_shadow_validation_candidate_overlay_fn,
        parse_optional_int_fn=parse_optional_int_fn,
        build_change_request_patch_artifacts_fn=lambda **kwargs: (
            build_change_request_patch_artifacts_with_context_fn(cur, **kwargs)
        ),
        suggest_change_request_draft_from_workflow_proposal_fn=lambda **kwargs: (
            suggest_change_request_draft_from_workflow_proposal_with_context_fn(cur, **kwargs)
        ),
        attach_patch_artifacts_to_change_request_draft_fn=lambda **kwargs: (
            attach_patch_artifacts_to_change_request_draft_with_context_fn(cur, kwargs["draft"])
        ),
    )
