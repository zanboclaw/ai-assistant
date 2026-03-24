from __future__ import annotations

import sys
from pathlib import Path

from fastapi import HTTPException

API_ROOT = Path(__file__).resolve().parents[1] / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from api_change_apply_runtime import (
    apply_change_request_payload_with_context,
    create_and_apply_automatic_rollback_change_request,
    process_change_request_post_apply_with_context,
    update_applied_change_request_row,
    update_reviewed_change_request_row,
)


class FakeCursor:
    def __init__(self, *, fetchone_results=None):
        self.fetchone_results = list(fetchone_results or [])
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((" ".join(str(sql).split()), params))

    def fetchone(self):
        if self.fetchone_results:
            return self.fetchone_results.pop(0)
        return None


def test_apply_change_request_payload_with_context_binds_cur_to_apply_helpers():
    bound_calls = []
    normalize_fn = lambda payload: {"normalized": payload}

    result = apply_change_request_payload_with_context(
        "cursor",
        "sandbox_file",
        "docs/example.md",
        {"exists": True},
        apply_change_request_payload_fn=lambda **kwargs: (
            kwargs["apply_sandbox_file_payload_fn"]("docs/example.md", {"exists": True}),
            kwargs["apply_risk_policy_fn"]("policy", {"enabled": True}),
            kwargs["apply_tool_registry_fn"]("tool", {"enabled": True}),
            kwargs["apply_model_route_fn"]("planner", {"enabled": True}),
            kwargs["apply_model_provider_fn"]("provider", {"enabled": True}),
            kwargs["apply_access_quota_fn"]("alice", {"daily_task_limit": 1}),
            kwargs["apply_access_actor_fn"]("alice", {"role": "admin"}),
            kwargs["normalize_sandbox_file_payload_fn"]({"exists": True}),
            "ok",
        )[-1],
        normalize_sandbox_file_payload_fn=normalize_fn,
        apply_sandbox_file_payload_fn=lambda current_target_key, normalized_payload: bound_calls.append(
            ("sandbox", current_target_key, normalized_payload)
        ),
        apply_risk_policy_payload_fn=lambda cur, current_target_key, current_payload: bound_calls.append(
            ("risk", cur, current_target_key, current_payload)
        ),
        apply_tool_registry_payload_fn=lambda cur, current_target_key, current_payload: bound_calls.append(
            ("tool", cur, current_target_key, current_payload)
        ),
        apply_model_route_payload_fn=lambda cur, current_target_key, current_payload: bound_calls.append(
            ("route", cur, current_target_key, current_payload)
        ),
        apply_model_provider_payload_fn=lambda cur, current_target_key, current_payload: bound_calls.append(
            ("provider", cur, current_target_key, current_payload)
        ),
        apply_access_quota_payload_fn=lambda cur, current_target_key, current_payload: bound_calls.append(
            ("quota", cur, current_target_key, current_payload)
        ),
        apply_access_actor_payload_fn=lambda cur, current_target_key, current_payload: bound_calls.append(
            ("actor", cur, current_target_key, current_payload)
        ),
    )

    assert result == "ok"
    assert bound_calls[0] == ("sandbox", "docs/example.md", {"exists": True})
    assert bound_calls[1] == ("risk", "cursor", "policy", {"enabled": True})
    assert bound_calls[-1] == ("actor", "cursor", "alice", {"role": "admin"})


def test_create_and_apply_automatic_rollback_change_request_updates_row_and_audits():
    cursor = FakeCursor(
        fetchone_results=[
            {"id": 42, "patch_summary": "applied rollback"},
        ]
    )
    audit_calls = []
    apply_calls = []

    result = create_and_apply_automatic_rollback_change_request(
        cursor,
        source_change_request={
            "id": 7,
            "target_type": "model_route",
            "target_key": "planner",
            "source_workflow_proposal_id": 99,
        },
        actor_name="local_admin",
        reason="shadow validation failed",
        build_change_request_rollback_draft_fn=lambda source_change_request: {
            "rollback_ready": True,
            "rollback_note": "ready",
            "target_type": source_change_request["target_type"],
            "target_key": source_change_request["target_key"],
            "proposed_payload": {"enabled": False},
            "rationale": "restore previous route",
        },
        create_change_request_row_fn=lambda cur, **kwargs: {"id": 42, "patch_summary": "created rollback", **kwargs},
        serialize_change_request_row_fn=lambda row: {
            "id": row["id"],
            "patch_summary": row["patch_summary"],
        },
        insert_audit_log_fn=lambda cur, event_type, actor_name, task_id, details: audit_calls.append(
            (event_type, actor_name, task_id, details)
        ),
        fetch_change_target_state_for_rollback_with_context_fn=lambda cur, **kwargs: {
            "target_type": kwargs["target_type"],
            "target_key": kwargs["target_key"],
            "enabled": True,
        },
        apply_change_request_payload_with_context_fn=lambda cur, target_type, target_key, payload: apply_calls.append(
            (cur, target_type, target_key, payload)
        ),
        safe_json_dumps_fn=lambda value: {"json": value},
        change_request_select_fields="id, patch_summary",
        http_exception_cls=HTTPException,
    )

    assert result == {"id": 42, "patch_summary": "applied rollback"}
    assert len(cursor.executed) == 1
    assert "UPDATE change_requests" in cursor.executed[0][0]
    assert apply_calls == [(cursor, "model_route", "planner", {"enabled": False})]
    assert [event for event, *_ in audit_calls] == [
        "change_request.rollback_create",
        "change_request.apply",
        "change_request.auto_rollback_apply",
    ]
    assert audit_calls[1][3]["rollback_ready"] is True


def test_create_and_apply_automatic_rollback_change_request_rejects_non_ready_draft():
    try:
        create_and_apply_automatic_rollback_change_request(
            "cursor",
            source_change_request={"id": 3, "target_type": "risk_policy", "target_key": "planner"},
            actor_name="local_admin",
            reason="manual rollback",
            build_change_request_rollback_draft_fn=lambda _source_change_request: {
                "rollback_ready": False,
                "rollback_note": "missing baseline",
            },
            create_change_request_row_fn=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not create")),
            serialize_change_request_row_fn=lambda row: row,
            insert_audit_log_fn=lambda *args, **kwargs: None,
            fetch_change_target_state_for_rollback_with_context_fn=lambda *args, **kwargs: {},
            apply_change_request_payload_with_context_fn=lambda *args, **kwargs: None,
            safe_json_dumps_fn=lambda value: value,
            change_request_select_fields="id",
            http_exception_cls=HTTPException,
        )
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail == "missing baseline"
    else:  # pragma: no cover
        raise AssertionError("expected HTTPException")


def test_process_change_request_post_apply_with_context_binds_cur_for_audit_and_rollback():
    calls = []

    result = process_change_request_post_apply_with_context(
        "cursor",
        change_request_id=5,
        change_request={"target_type": "sandbox_file", "target_key": "docs/test.md"},
        normalized_proposed_payload={"exists": True},
        rollback_payload={"exists": True},
        rollback_ready=True,
        rollback_note="ready",
        actor_name="local_admin",
        process_change_request_post_apply_fn=lambda **kwargs: (
            kwargs["insert_audit_log_fn"]("change_request.acceptance", "local_admin", None, {"ok": True}),
            kwargs["create_and_apply_automatic_rollback_change_request_fn"](source_change_request={"id": 7}, actor_name="local_admin", reason="failed"),
            {"status": "processed"},
        )[-1],
        execute_sandbox_file_acceptance_fn=lambda **kwargs: ("passed", {"ok": True}, None),
        make_json_compatible_fn=lambda value: value,
        insert_audit_log_fn=lambda cur, event_type, actor_name, task_id, details: calls.append(
            ("audit", cur, event_type, actor_name, task_id, details)
        ),
        create_and_apply_automatic_rollback_change_request_fn=lambda cur, **kwargs: calls.append(
            ("rollback", cur, kwargs)
        ),
    )

    assert result == {"status": "processed"}
    assert calls[0][0] == "audit"
    assert calls[0][1] == "cursor"
    assert calls[1] == ("rollback", "cursor", {"source_change_request": {"id": 7}, "actor_name": "local_admin", "reason": "failed"})


def test_update_reviewed_and_applied_change_request_rows_execute_expected_sql():
    cursor = FakeCursor(
        fetchone_results=[
            {"id": 5, "status": "approved"},
            {"id": 5, "status": "applied"},
        ]
    )

    reviewed = update_reviewed_change_request_row(
        cursor,
        change_request_id=5,
        actor_name="local_admin",
        note="approve",
        next_status="approved",
        change_request_select_fields="id, status",
    )
    applied = update_applied_change_request_row(
        cursor,
        change_request_id=5,
        actor_name="local_admin",
        rollback_payload={"enabled": False},
        rollback_ready=True,
        rollback_note="captured",
        acceptance_status="passed",
        acceptance_report="{}",
        acceptance_at="2026-03-25T10:00:00Z",
        auto_rollback_change_request_id=11,
        auto_rollback_at="2026-03-25T10:01:00Z",
        safe_json_dumps_fn=lambda value: {"json": value},
        change_request_select_fields="id, status",
    )

    assert reviewed == {"id": 5, "status": "approved"}
    assert applied == {"id": 5, "status": "applied"}
    assert "reviewed_by_actor" in cursor.executed[0][0]
    assert cursor.executed[1][1][1] == {"json": {"enabled": False}}
