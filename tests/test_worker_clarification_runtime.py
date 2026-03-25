from worker import fail_task_for_missing_clarification


class FakeConnection:
    def __init__(self):
        self.commit_called = 0

    def commit(self):
        self.commit_called += 1


class FakeCursor:
    def __init__(self):
        self.connection = FakeConnection()


def test_fail_task_for_missing_clarification_marks_waiting_clarification(monkeypatch):
    cur = FakeCursor()
    calls = []

    monkeypatch.setattr("worker_runtime_context.ensure_task_trace", lambda *_args, **_kwargs: calls.append(("ensure_trace", 33)))
    monkeypatch.setattr("worker_runtime_context.update_task_delivery_records", lambda *_args, **kwargs: calls.append(("delivery", kwargs["recovery_action"]["action"])))
    monkeypatch.setattr(
        "worker_runtime_context.persist_task_runtime_state",
        lambda _cur, task_id, user_input, **kwargs: calls.append(("persist", task_id, user_input, kwargs["status"])),
    )
    monkeypatch.setattr(
        "worker_runtime_context.update_task_trace_status",
        lambda _cur, task_id, **kwargs: calls.append(("trace_status", task_id, kwargs["status"])),
    )
    monkeypatch.setattr(
        "worker_runtime_context.insert_audit_log",
        lambda _cur, event_type, actor, task_id, details: calls.append(("audit", event_type, actor, task_id, details["recovery_action"]["action"])),
    )

    fail_task_for_missing_clarification(
        cur,
        33,
        "帮我规划一次上线",
        task_intent={
            "needs_clarification": True,
            "clarification_reasons": ["缺少上线窗口"],
        },
        deliverable_spec={
            "deliverable_type": "research_summary",
            "clarify": {"questions": ["请提供上线窗口"]},
        },
    )

    assert ("persist", 33, "帮我规划一次上线", "waiting_clarification") in calls
    assert ("trace_status", 33, "waiting_clarification") in calls
    assert cur.connection.commit_called == 1
