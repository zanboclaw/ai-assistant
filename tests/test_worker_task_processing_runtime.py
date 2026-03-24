from task_processing_runtime import process_task


class FakeConn:
    def __init__(self):
        self.closed = False
        self.cursor_instance = FakeCursor(self)
        self.commit_called = 0

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commit_called += 1

    def close(self):
        self.closed = True


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.closed = False

    def close(self):
        self.closed = True


class FakeLogger:
    def __init__(self):
        self.messages = []

    def info(self, message, *args):
        self.messages.append(("info", message % args if args else message))

    def warning(self, message, *args):
        self.messages.append(("warning", message % args if args else message))

    def exception(self, message, *args):
        self.messages.append(("exception", message % args if args else message))


def test_process_task_stops_on_blocking_clarification():
    conn = FakeConn()
    logger = FakeLogger()
    calls = []

    process_task(
        {"id": 33, "user_input": "帮我调研一下"},
        None,
        get_conn=lambda: conn,
        logger=logger,
        augment_user_input_with_memory_context=lambda user_input, _task: user_input,
        extract_task_model_route_overrides=lambda _task: {},
        extract_task_skill_invocation=lambda _task: {},
        extract_task_intent=lambda _task: {"needs_clarification": True},
        extract_deliverable_spec=lambda _task: {"clarify": {"blocking": True}},
        ensure_task_steps_columns=lambda _cur: calls.append("ensure_steps"),
        ensure_approvals_table=lambda _cur: calls.append("ensure_approvals"),
        seed_default_tool_registry=lambda _cur: calls.append("seed_tools"),
        seed_default_model_providers=lambda _cur: calls.append("seed_providers"),
        seed_default_model_routes=lambda _cur: calls.append("seed_routes"),
        fetch_latest_evaluator_feedback=lambda _cur, _task_id: {},
        augment_user_input_with_runtime_feedback=lambda planner_user_input, _latest: planner_user_input,
        fail_task_for_missing_clarification=lambda _cur, task_id, planner_user_input, **_kwargs: calls.append(
            ("clarify", task_id, planner_user_input)
        ),
        start_task_execution=lambda *_args, **_kwargs: calls.append("should_not_start"),
        set_current_trace_context=lambda **_kwargs: calls.append("should_not_trace"),
        clear_current_trace_context=lambda: calls.append("should_not_clear"),
        select_task_plan_source=lambda *_args, **_kwargs: calls.append("should_not_plan"),
        run_planned_execution=lambda *_args, **_kwargs: calls.append("should_not_run"),
        finalize_task_success=lambda *_args, **_kwargs: calls.append("should_not_finalize"),
        finalize_task_failure=lambda *_args, **_kwargs: calls.append("should_not_fail"),
        maybe_dispatch_task_runtime_specialists=lambda *_args, **_kwargs: calls.append("should_not_dispatch"),
        approval_required_exc_type=RuntimeError,
        interrupt_requested_exc_type=InterruptedError,
        auto_recovery_scheduled_exc_type=ValueError,
        claim_lost_exc_type=KeyError,
    )

    assert ("clarify", 33, "帮我调研一下") in calls
    assert "should_not_start" not in calls
    assert conn.cursor_instance.closed is True
    assert conn.closed is True
