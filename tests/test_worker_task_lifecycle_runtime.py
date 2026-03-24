from task_lifecycle_runtime import finalize_task_failure, persist_task_runtime_state, start_task_execution


class FakeConn:
    def __init__(self):
        self.rollback_called = 0
        self.commit_called = 0

    def rollback(self):
        self.rollback_called += 1

    def commit(self):
        self.commit_called += 1

    def cursor(self):
        return FakeCursor(self)


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.closed = False

    def close(self):
        self.closed = True


class FakeLogger:
    def __init__(self):
        self.messages = []

    def warning(self, message, *args):
        self.messages.append(message % args if args else message)


def test_persist_task_runtime_state_updates_status_checkpoint_and_commits():
    conn = FakeConn()
    cur = FakeCursor(conn)
    calls = []

    persist_task_runtime_state(
        cur,
        55,
        "整理版本说明",
        status="running",
        current_step=3,
        step_context={3: {"output_payload": "done"}},
        var_context={"region": "cn"},
        step_outputs=["done"],
        task_error_message=None,
        checkpoint_error="",
        update_task_status=lambda _cur, task_id, status, result, error: calls.append(
            ("status", task_id, status, result, error)
        ),
        write_checkpoint=lambda _cur, task_id, user_input, status, current_step, _step_context, _var_context, _step_outputs, checkpoint_error: calls.append(
            ("checkpoint", task_id, user_input, status, current_step, checkpoint_error)
        ),
        result="ok",
    )

    assert calls == [
        ("status", 55, "running", "ok", None),
        ("checkpoint", 55, "整理版本说明", "running", 3, ""),
    ]
    assert conn.commit_called == 1


def test_start_task_execution_delegates_trace_and_runtime_persistence():
    cur = FakeCursor(FakeConn())
    calls = []

    start_task_execution(
        cur,
        18,
        "整理发布窗口说明",
        ensure_task_trace=lambda _cur, task_id, user_input: calls.append(("trace", task_id, user_input)),
        persist_task_runtime_state=lambda _cur, task_id, user_input, **kwargs: calls.append(("persist", task_id, user_input, kwargs["status"])),
        update_task_trace_status=lambda _cur, task_id, **kwargs: calls.append(("trace_status", task_id, kwargs["status"])),
    )

    assert calls == [
        ("trace", 18, "整理发布窗口说明"),
        ("persist", 18, "整理发布窗口说明", "running"),
        ("trace_status", 18, "running"),
    ]


def test_finalize_task_failure_writes_failure_records_and_commits():
    conn = FakeConn()
    cur = FakeCursor(conn)
    logger = FakeLogger()
    calls = []

    finalize_task_failure(
        cur,
        88,
        "帮我找几个小红书文案",
        {},
        {},
        [],
        "worker exploded",
        build_runtime_failure_validation_report=lambda err: {"passed": False, "error": err},
        build_runtime_failure_recovery_action=lambda err: {"action": "retry", "error": err},
        update_task_delivery_records=lambda _cur, task_id, **kwargs: calls.append(("delivery", task_id, kwargs["recovery_action"]["action"])),
        persist_task_runtime_state=lambda _cur, task_id, user_input, **kwargs: calls.append(("persist", task_id, user_input, kwargs["status"])),
        update_task_trace_status=lambda _cur, task_id, **kwargs: calls.append(("trace_status", task_id, kwargs["status"])),
        insert_audit_log=lambda _cur, event_type, actor, task_id, details: calls.append(("audit", event_type, actor, task_id, details["recovery_action"]["action"])),
        maybe_create_task_postrun_agent_records=lambda _cur, task_id, user_input: calls.append(("postrun", task_id, user_input)),
        logger=logger,
    )

    assert conn.rollback_called == 1
    assert conn.commit_called == 1
    assert ("delivery", 88, "retry") in calls
    assert ("persist", 88, "帮我找几个小红书文案", "failed") in calls
    assert ("trace_status", 88, "failed") in calls
    assert ("postrun", 88, "帮我找几个小红书文案") in calls
