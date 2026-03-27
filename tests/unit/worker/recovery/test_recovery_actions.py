from apps.worker.runtime.recovery.recovery_actions import reset_task_for_auto_recovery, trim_runtime_state_for_resume


class FakeConnection:
    def __init__(self):
        self.commit_called = 0

    def commit(self):
        self.commit_called += 1


class FakeCursor:
    def __init__(self):
        self.connection = FakeConnection()
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((" ".join(str(sql).split()), params))


def test_trim_runtime_state_for_resume_keeps_completed_prefix():
    step_context, var_context, step_outputs = trim_runtime_state_for_resume(
        resume_from=3,
        step_context={1: {"status": "completed"}, 2: {"status": "completed"}, 3: {"status": "failed"}},
        var_context={"region": "cn"},
        step_outputs=["a", "b", "c"],
    )

    assert list(step_context) == [1, 2]
    assert var_context == {"region": "cn"}
    assert step_outputs == ["a", "b"]


def test_reset_task_for_auto_recovery_resets_future_steps_and_requeues():
    cur = FakeCursor()
    calls = []

    reset_task_for_auto_recovery(
        cur,
        task_id=88,
        user_input="整理发布方案",
        resume_from=2,
        step_context={1: {"status": "completed"}, 2: {"status": "failed"}},
        var_context={"region": "cn"},
        step_outputs=["done", "retry"],
        note="auto recovery scheduled: retry_generate",
        recovery_action={"action": "retry_generate"},
        persist_task_runtime_state=lambda _cur, task_id, user_input, **kwargs: calls.append(
            ("persist", task_id, user_input, kwargs["current_step"], kwargs["status"], kwargs["step_outputs"])
        ),
        update_task_trace_status=lambda _cur, task_id, **kwargs: calls.append(("trace_status", task_id, kwargs["status"])),
        insert_audit_log=lambda _cur, event_type, actor, task_id, details: calls.append(
            ("audit", event_type, actor, task_id, details["recovery_action"]["action"])
        ),
        enqueue_task=lambda task_id: calls.append(("enqueue", task_id)),
    )

    assert any("UPDATE task_steps" in sql for sql, _params in cur.executed)
    assert ("persist", 88, "整理发布方案", 2, "pending", ["done"]) in calls
    assert ("trace_status", 88, "pending") in calls
    assert ("enqueue", 88) in calls
    assert cur.connection.commit_called == 1
