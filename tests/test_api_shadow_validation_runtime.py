from __future__ import annotations

import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1] / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from api_shadow_validation_runtime import (
    build_change_request_shadow_validation_state_with_context,
    build_shadow_validation_execution_payload_with_context,
    fetch_shadow_task_and_evaluator_with_context,
    fetch_latest_workflow_proposal_shadow_validation_with_context,
    finalize_shadow_validation_response_with_context,
    record_shadow_validation_result_with_context,
    start_shadow_validation_completion_worker,
    sync_change_requests_shadow_validation_with_context,
    wait_for_shadow_validation_completion_with_context,
)


def test_fetch_latest_workflow_proposal_shadow_validation_with_context_passes_history_loader():
    calls = []

    result = fetch_latest_workflow_proposal_shadow_validation_with_context(
        object(),
        17,
        fetch_latest_workflow_proposal_shadow_validation_fn=lambda cur, proposal_id, **kwargs: calls.append(
            (cur, proposal_id, kwargs)
        )
        or {"proposal_id": proposal_id},
        fetch_workflow_proposal_shadow_validation_history_with_context_fn=lambda *_args, **_kwargs: [],
        shadow_validation_candidate_matches_fn=lambda **_kwargs: True,
        result_event="workflow_proposal.shadow_validated",
        target_type="model_route",
        target_key="planner",
        proposed_payload={"enabled": True},
        history_limit=12,
    )

    assert result == {"proposal_id": 17}
    assert calls[0][1] == 17
    assert calls[0][2]["history_limit"] == 12
    assert callable(calls[0][2]["fetch_workflow_proposal_shadow_validation_history_fn"])


def test_build_change_request_shadow_validation_state_with_context_wraps_followup_loader():
    calls = []

    result = build_change_request_shadow_validation_state_with_context(
        "cursor",
        build_change_request_shadow_validation_state_fn=lambda **kwargs: calls.append(kwargs) or {"status": "ready"},
        normalize_change_request_proposal_kind_fn=lambda value: value or "manual_change",
        change_request_requires_shadow_validation_fn=lambda _value: True,
        fetch_latest_workflow_proposal_shadow_validation_with_context_fn=lambda cur, proposal_id, **kwargs: {
            "cur": cur,
            "proposal_id": proposal_id,
            **kwargs,
        },
        annotate_shadow_validation_report_for_change_request_fn=lambda validation_report, **kwargs: {
            "validation_report": validation_report,
            **kwargs,
        },
        proposal_kind="workflow_proposal",
        source_workflow_proposal_id=5,
        target_type="model_route",
        target_key="planner",
        proposed_payload={"enabled": False},
    )

    assert result["status"] == "ready"
    fetcher = calls[0]["fetch_latest_workflow_proposal_shadow_validation_fn"]
    assert fetcher(8, history_limit=3)["cur"] == "cursor"
    assert fetcher(8, history_limit=3)["proposal_id"] == 8


def test_sync_change_requests_shadow_validation_with_context_wraps_state_builder():
    calls = []

    result = sync_change_requests_shadow_validation_with_context(
        "cursor",
        23,
        sync_change_requests_shadow_validation_fn=lambda cur, proposal_id, **kwargs: calls.append(
            (cur, proposal_id, kwargs)
        )
        or 2,
        ensure_change_requests_table_fn=lambda _cur: None,
        parse_maybe_json_fn=lambda value: value,
        parse_optional_int_fn=lambda value: value,
        build_change_request_shadow_validation_state_with_context_fn=lambda cur, **kwargs: {
            "cur": cur,
            **kwargs,
        },
        safe_json_dumps_fn=lambda value: value,
    )

    assert result == 2
    builder = calls[0][2]["build_change_request_shadow_validation_state_fn"]
    assert builder(source_workflow_proposal_id=7)["cur"] == "cursor"


def test_fetch_shadow_task_and_evaluator_with_context_uses_fresh_connection():
    class FakeCursor:
        def __init__(self):
            self.executed = []
            self.closed = False

        def execute(self, sql, params=None):
            self.executed.append((" ".join(str(sql).split()), params))

        def fetchone(self):
            return {"id": 19, "status": "completed"}

        def close(self):
            self.closed = True

    class FakeConn:
        def __init__(self):
            self.cursor_instance = FakeCursor()
            self.closed = False

        def cursor(self):
            return self.cursor_instance

        def close(self):
            self.closed = True

    conn = FakeConn()
    result = fetch_shadow_task_and_evaluator_with_context(
        19,
        get_conn_fn=lambda: conn,
        fetch_latest_evaluator_for_task_fn=lambda cur, task_id: {"cur": cur, "task_id": task_id},
    )

    assert result[0]["id"] == 19
    assert result[1]["task_id"] == 19
    assert conn.cursor_instance.closed is True
    assert conn.closed is True


def test_record_shadow_validation_result_with_context_commits_audit_and_sync():
    calls = []

    class FakeCursor:
        def close(self):
            calls.append("cursor_closed")

    class FakeConn:
        def __init__(self):
            self.cursor_instance = FakeCursor()

        def cursor(self):
            return self.cursor_instance

        def commit(self):
            calls.append("commit")

        def close(self):
            calls.append("conn_closed")

    record_shadow_validation_result_with_context(
        workflow_proposal={"id": 22},
        baseline_task_id=5,
        actor_name="local_admin",
        validation={"score": 80},
        get_conn_fn=lambda: FakeConn(),
        insert_audit_log_fn=lambda cur, event_type, actor_name, task_id, details: calls.append(
            ("audit", cur, event_type, actor_name, task_id, details)
        ),
        sync_change_requests_shadow_validation_with_context_fn=lambda cur, proposal_id: calls.append(
            ("sync", cur, proposal_id)
        ),
    )

    assert calls[0][0] == "audit"
    assert calls[1] == ("sync", calls[0][1], 22)
    assert "commit" in calls


def test_wait_for_shadow_validation_completion_with_context_passes_bound_helpers():
    calls = []

    result = wait_for_shadow_validation_completion_with_context(
        workflow_proposal={"id": 7},
        baseline_task_id=3,
        shadow_task_id=4,
        actor_name="alice",
        timeout_seconds=30,
        poll_interval_seconds=1.5,
        candidate_overlay={"target_key": "planner"},
        runtime_overrides={"shadow": True},
        validation_mode="task_replay_compare",
        wait_for_shadow_validation_completion_fn=lambda **kwargs: calls.append(kwargs) or {"completed": True},
        fetch_shadow_task_and_evaluator_with_context_fn=lambda shadow_task_id: ({"id": shadow_task_id}, {"decision": "pass"}),
        build_shadow_validation_result_fn=lambda **kwargs: kwargs,
        record_shadow_validation_result_with_context_fn=lambda **kwargs: None,
    )

    assert result == {"completed": True}
    assert callable(calls[0]["fetch_shadow_task_and_evaluator_fn"])
    assert callable(calls[0]["record_shadow_validation_result_fn"])


def test_start_shadow_validation_completion_worker_starts_named_thread():
    thread_calls = []

    class FakeThread:
        def __init__(self, *, target, name, daemon):
            thread_calls.append((name, daemon))
            self._target = target

        def start(self):
            thread_calls.append("started")
            self._target()

    class FakeLogger:
        def exception(self, *_args, **_kwargs):
            thread_calls.append("logged")

    wait_calls = []
    start_shadow_validation_completion_worker(
        workflow_proposal={"id": 8},
        baseline_task_id=2,
        shadow_task_id=31,
        actor_name="bob",
        timeout_seconds=40,
        poll_interval_seconds=2.0,
        candidate_overlay={"target_key": "planner"},
        runtime_overrides={"shadow": True},
        validation_mode="task_replay_compare",
        wait_for_shadow_validation_completion_with_context_fn=lambda **kwargs: wait_calls.append(kwargs),
        thread_cls=FakeThread,
        logger=FakeLogger(),
    )

    assert thread_calls[0] == ("shadow-validation-31", True)
    assert thread_calls[1] == "started"
    assert wait_calls[0]["shadow_task_id"] == 31


def test_build_and_finalize_shadow_validation_context_helpers_delegate():
    execution_calls = []
    final_calls = []

    payload = build_shadow_validation_execution_payload_with_context(
        workflow_proposal={"id": 9},
        baseline_task={"id": 3},
        request=object(),
        actor={"actor_name": "local_admin"},
        quota_snapshot={"daily_task_limit": 5},
        candidate_overlay={"target_key": "planner"},
        runtime_overrides={"shadow": True},
        shadow_task={"id": 10},
        build_shadow_validation_execution_payload_fn=lambda **kwargs: execution_calls.append(kwargs) or {"payload": True},
        parse_optional_int_fn=lambda value: value,
        make_json_compatible_fn=lambda value: value,
    )
    response = finalize_shadow_validation_response_with_context(
        workflow_proposal={"id": 9},
        baseline_task={"id": 3},
        shadow_task={"id": 10},
        validation_request={"proposal_id": 9},
        candidate_overlay={"target_key": "planner"},
        validation_mode="task_replay_compare",
        source_change_request={"id": 4},
        await_completion=False,
        actor_name="local_admin",
        timeout_seconds=15,
        poll_interval_seconds=1.0,
        runtime_overrides={"shadow": True},
        finalize_shadow_validation_response_fn=lambda **kwargs: final_calls.append(kwargs) or {"completed": False},
        make_json_compatible_fn=lambda value: {"wrapped": value},
        wait_for_shadow_validation_completion_with_context_fn=lambda **kwargs: kwargs,
        start_shadow_validation_completion_worker_fn=lambda **kwargs: kwargs,
    )

    assert payload == {"payload": True}
    assert execution_calls[0]["make_json_compatible_fn"]({"ok": True}) == {"ok": True}
    assert response == {"completed": False}
    assert final_calls[0]["candidate_overlay"] == {"wrapped": {"target_key": "planner"}}
