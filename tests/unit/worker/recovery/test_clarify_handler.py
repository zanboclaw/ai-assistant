from apps.worker.runtime.recovery.clarify_handler import fail_task_for_missing_clarification


class FakeConnection:
    def __init__(self):
        self.commit_called = 0

    def commit(self):
        self.commit_called += 1


class FakeCursor:
    def __init__(self):
        self.connection = FakeConnection()


def test_clarify_handler_marks_waiting_state_and_audits():
    cur = FakeCursor()
    calls = []

    fail_task_for_missing_clarification(
        cur,
        101,
        "帮我规划一次上线",
        task_intent={"needs_clarification": True},
        deliverable_spec={"deliverable_type": "research_summary", "clarify": {"questions": ["请提供上线窗口"]}},
        ensure_task_trace=lambda *_args, **_kwargs: calls.append("trace"),
        build_clarification_required_validation_report=lambda *_args, **_kwargs: {"passed": False},
        build_clarification_required_recovery_action=lambda *_args, **_kwargs: {"action": "clarify", "summary": "need clarify"},
        build_clarification_required_message=lambda *_args, **_kwargs: "请补充信息",
        update_task_delivery_records=lambda _cur, task_id, **kwargs: calls.append(
            ("delivery", task_id, kwargs["recovery_action"]["action"])
        ),
        persist_task_runtime_state=lambda _cur, task_id, user_input, **kwargs: calls.append(
            ("persist", task_id, user_input, kwargs["status"], kwargs["result"])
        ),
        update_task_trace_status=lambda _cur, task_id, **kwargs: calls.append(("trace_status", task_id, kwargs["status"])),
        insert_audit_log=lambda _cur, event_type, actor, task_id, details: calls.append(
            ("audit", event_type, actor, task_id, details["recovery_action"]["action"])
        ),
    )

    assert ("delivery", 101, "clarify") in calls
    assert ("persist", 101, "帮我规划一次上线", "waiting_clarification", "请补充信息") in calls
    assert ("trace_status", 101, "waiting_clarification") in calls
    assert cur.connection.commit_called == 1

