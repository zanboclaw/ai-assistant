from __future__ import annotations

import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1] / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from api_change_request_runtime import (
    create_change_request_row,
    fetch_change_target_state_for_rollback_with_context,
    resolve_shadow_validation_candidate_overlay_with_context,
)


def test_create_change_request_row_builds_payload_and_inserts():
    calls = []

    result = create_change_request_row(
        "cursor",
        ensure_change_requests_table_fn=lambda _cur: calls.append("ensure"),
        normalize_change_request_proposal_kind_fn=lambda value: f"normalized:{value}",
        build_change_request_create_payload_fn=lambda **kwargs: calls.append(kwargs) or {"payload": "ok"},
        normalize_change_request_payload_fn=lambda target_type, payload: {"target_type": target_type, **(payload or {})},
        build_change_request_patch_artifacts_with_context_fn=lambda cur, **kwargs: {"cur": cur, **kwargs},
        build_change_request_shadow_validation_state_with_context_fn=lambda cur, **kwargs: {"cur": cur, **kwargs},
        insert_change_request_row_fn=lambda cur, **kwargs: {"cur": cur, **kwargs},
        safe_json_dumps_fn=lambda value: value,
        target_type="model_route",
        target_key="planner",
        proposed_payload={"enabled": True},
        rationale="sync planner route",
        requested_by_actor="local_admin",
        proposal_kind="manual_change",
    )

    assert calls[0] == "ensure"
    assert calls[1]["proposal_kind"] == "normalized:manual_change"
    assert result["change_request_payload"] == {"payload": "ok"}


def test_fetch_change_target_state_for_rollback_with_context_passes_all_serializers():
    captured = []

    result = fetch_change_target_state_for_rollback_with_context(
        "cursor",
        fetch_change_target_state_for_rollback_fn=lambda cur, **kwargs: captured.append((cur, kwargs)) or {
            "target_type": kwargs["target_type"],
            "target_key": kwargs["target_key"],
        },
        fetch_sandbox_file_state_fn=lambda target_key: {"target_key": target_key},
        seed_default_risk_policies_fn=lambda _cur: None,
        deserialize_policy_row_fn=lambda row: row,
        seed_default_tool_registry_fn=lambda _cur: None,
        serialize_tool_registry_row_fn=lambda row: row,
        seed_default_model_providers_fn=lambda _cur: None,
        seed_default_model_routes_fn=lambda _cur: None,
        serialize_model_route_row_fn=lambda row: row,
        serialize_model_provider_row_fn=lambda row: row,
        seed_default_access_quotas_fn=lambda _cur: None,
        serialize_access_quota_row_fn=lambda row: row,
        seed_default_access_actors_fn=lambda _cur: None,
        serialize_access_actor_row_fn=lambda row: row,
        target_type="sandbox_file",
        target_key="docs/README.md",
    )

    assert result["target_key"] == "docs/README.md"
    assert captured[0][0] == "cursor"
    assert callable(captured[0][1]["fetch_sandbox_file_state_fn"])


def test_resolve_shadow_validation_candidate_overlay_with_context_wraps_cur_bound_helpers():
    captured = []

    result = resolve_shadow_validation_candidate_overlay_with_context(
        "cursor",
        resolve_shadow_validation_candidate_overlay_fn=lambda **kwargs: captured.append(kwargs) or {
            "overlay": "ok"
        },
        build_shadow_validation_candidate_overlay_fn=lambda **kwargs: kwargs,
        parse_optional_int_fn=lambda value: value,
        build_change_request_patch_artifacts_with_context_fn=lambda cur, **kwargs: {"cur": cur, **kwargs},
        suggest_change_request_draft_from_workflow_proposal_with_context_fn=lambda cur, **kwargs: {
            "cur": cur,
            **kwargs,
        },
        attach_patch_artifacts_to_change_request_draft_with_context_fn=lambda cur, draft: {
            "cur": cur,
            "draft": draft,
        },
        workflow_proposal={"id": 9},
        request={"mode": "latest"},
        source_change_request={"id": 3},
    )

    assert result["overlay"] == "ok"
    kwargs = captured[0]
    assert kwargs["build_change_request_patch_artifacts_fn"](target_key="planner")["cur"] == "cursor"
    assert kwargs["suggest_change_request_draft_from_workflow_proposal_fn"](draft_mode="auto")["cur"] == "cursor"
    assert kwargs["attach_patch_artifacts_to_change_request_draft_fn"](draft={"title": "x"})["cur"] == "cursor"
