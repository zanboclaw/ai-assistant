from change_request_business import (
    annotate_shadow_validation_report_for_change_request,
    build_change_request_rollback_draft,
)
from change_request_serializers import build_shadow_validation_candidate_overlay, shadow_validation_candidate_matches
from json_utils import compute_stable_payload_hash, make_json_compatible


def test_annotate_shadow_validation_report_marks_candidate_match():
    proposed_payload = {"enabled": True, "route": "planner"}
    candidate_overlay = build_shadow_validation_candidate_overlay(
        target_type="model_route",
        target_key="planner",
        proposed_payload=proposed_payload,
    )
    report = {"validation": {"candidate_overlay": candidate_overlay}}

    annotated = annotate_shadow_validation_report_for_change_request(
        report,
        target_type="model_route",
        target_key="planner",
        proposed_payload=proposed_payload,
        make_json_compatible_fn=make_json_compatible,
        shadow_validation_candidate_matches_fn=shadow_validation_candidate_matches,
        compute_stable_payload_hash_fn=compute_stable_payload_hash,
    )

    assert annotated["candidate_match"] is True
    assert annotated["current_change_request"]["proposed_payload_hash"] == compute_stable_payload_hash(proposed_payload)


def test_build_change_request_rollback_draft_only_ready_when_payload_present():
    draft = build_change_request_rollback_draft(
        {
            "id": 12,
            "target_type": "model_route",
            "target_key": "planner",
            "rollback_payload": {"provider": "deepseek"},
            "rollback_ready": True,
            "rollback_note": "restore previous provider",
            "source_workflow_proposal_id": 7,
        }
    )

    assert draft["rollback_ready"] is True
    assert draft["proposal_kind"] == "rollback"
    assert draft["source_change_request"]["id"] == 12
