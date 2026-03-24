from __future__ import annotations

import json

from fastapi import HTTPException

from task_control_runtime import (
    get_task_or_404,
    reset_task_for_clarification,
    reset_task_for_resume,
    resolve_resume_from_step,
    update_checkpoint_status,
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


def test_get_task_or_404_raises_when_missing():
    cursor = FakeCursor(fetchone_results=[None])

    try:
        get_task_or_404(cursor, 99, http_exception_cls=HTTPException)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:  # pragma: no cover
        raise AssertionError("expected HTTPException")


def test_resolve_resume_from_step_prefers_first_non_completed_step():
    cursor = FakeCursor(fetchone_results=[{"step_order": 4}])

    assert resolve_resume_from_step(cursor, 11, None) == 4
    assert resolve_resume_from_step(cursor, 11, 2) == 2


def test_reset_task_for_resume_updates_steps_and_audit():
    cursor = FakeCursor()
    audit_calls = []

    reset_task_for_resume(
        cursor,
        task_id=7,
        task={"status": "failed"},
        resume_from=3,
        actor={"actor_name": "local_admin", "role": "admin"},
        note="retry",
        event_type="task.resume",
        insert_audit_log_fn=lambda _cur, event_type, actor_name, task_id, details: audit_calls.append(
            (event_type, actor_name, task_id, details)
        ),
        details={"reason": "manual"},
    )

    assert len(cursor.executed) == 2
    assert audit_calls[0][0] == "task.resume"
    assert audit_calls[0][3]["from_step"] == 3


def test_reset_task_for_clarification_rewrites_payloads_and_audit():
    cursor = FakeCursor()
    audit_calls = []

    reset_task_for_clarification(
        cursor,
        task_id=5,
        task={"status": "waiting_approval"},
        actor={"actor_name": "alice", "role": "operator"},
        new_user_input="补充说明后的任务",
        task_intent={"task_type": "research"},
        deliverable_spec={"deliverable_type": "research_summary"},
        runtime_overrides={"mode": "clarified"},
        note="clarified",
        json_wrapper=lambda value: {"json": value},
        make_json_compatible=lambda value: value,
        insert_audit_log_fn=lambda _cur, event_type, actor_name, task_id, details: audit_calls.append(
            (event_type, actor_name, task_id, details)
        ),
    )

    assert len(cursor.executed) == 2
    update_params = cursor.executed[1][1]
    assert update_params[0] == "补充说明后的任务"
    assert audit_calls[0][0] == "task.clarify_resume"
    assert audit_calls[0][3]["deliverable_type"] == "research_summary"


def test_update_checkpoint_status_updates_json_file(tmp_path):
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint_path.write_text(json.dumps({"status": "running"}, ensure_ascii=False), encoding="utf-8")

    update_checkpoint_status(str(checkpoint_path), "paused", "manual stop")

    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert payload["status"] == "paused"
    assert payload["last_error"] == "manual stop"
    assert "updated_at" in payload
