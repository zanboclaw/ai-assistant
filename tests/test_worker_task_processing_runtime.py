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


def test_process_task_uses_raw_user_input_for_clarification_failure_even_when_planner_input_is_augmented():
    conn = FakeConn()
    logger = FakeLogger()
    calls = []

    process_task(
        {"id": 34, "user_input": "帮我调研一下"},
        None,
        get_conn=lambda: conn,
        logger=logger,
        augment_user_input_with_memory_context=lambda user_input, _task: f"{user_input}\n\n可复用的长期记忆：\n1. [memory] 不应写回澄清任务",
        extract_task_model_route_overrides=lambda _task: {},
        extract_task_skill_invocation=lambda _task: {},
        extract_task_intent=lambda _task: {"needs_clarification": True},
        extract_deliverable_spec=lambda _task: {"clarify": {"blocking": True}},
        ensure_task_steps_columns=lambda _cur: None,
        ensure_approvals_table=lambda _cur: None,
        seed_default_tool_registry=lambda _cur: None,
        seed_default_model_providers=lambda _cur: None,
        seed_default_model_routes=lambda _cur: None,
        fetch_latest_evaluator_feedback=lambda _cur, _task_id: {},
        augment_user_input_with_runtime_feedback=lambda planner_user_input, _latest: planner_user_input,
        fail_task_for_missing_clarification=lambda _cur, task_id, planner_user_input, **_kwargs: calls.append(
            ("clarify", task_id, planner_user_input)
        ),
        start_task_execution=lambda *_args, **_kwargs: None,
        set_current_trace_context=lambda **_kwargs: None,
        clear_current_trace_context=lambda: None,
        select_task_plan_source=lambda *_args, **_kwargs: None,
        run_planned_execution=lambda *_args, **_kwargs: ([], {}, {}),
        finalize_task_success=lambda *_args, **_kwargs: None,
        finalize_task_failure=lambda *_args, **_kwargs: None,
        maybe_dispatch_task_runtime_specialists=lambda *_args, **_kwargs: None,
        approval_required_exc_type=RuntimeError,
        interrupt_requested_exc_type=InterruptedError,
        auto_recovery_scheduled_exc_type=ValueError,
        claim_lost_exc_type=KeyError,
    )

    assert calls == [("clarify", 34, "帮我调研一下")]


def test_process_task_uses_runtime_loading_and_execution_plan_helpers():
    conn = FakeConn()
    logger = FakeLogger()
    calls = []

    process_task(
        {"id": 35, "user_input": "整理发布方案"},
        None,
        get_conn=lambda: conn,
        logger=logger,
        augment_user_input_with_memory_context=lambda user_input, _task: f"{user_input}\n\n记忆补充",
        extract_task_model_route_overrides=lambda _task: (_ for _ in ()).throw(AssertionError("should use runtime context")),
        extract_task_skill_invocation=lambda _task: (_ for _ in ()).throw(AssertionError("should use runtime context")),
        extract_task_intent=lambda _task: (_ for _ in ()).throw(AssertionError("should use runtime context")),
        extract_deliverable_spec=lambda _task: (_ for _ in ()).throw(AssertionError("should use runtime context")),
        ensure_task_steps_columns=lambda _cur: calls.append("ensure_steps"),
        ensure_approvals_table=lambda _cur: calls.append("ensure_approvals"),
        seed_default_tool_registry=lambda _cur: calls.append("seed_tools"),
        seed_default_model_providers=lambda _cur: calls.append("seed_providers"),
        seed_default_model_routes=lambda _cur: calls.append("seed_routes"),
        fetch_latest_evaluator_feedback=lambda _cur, _task_id: {"status": "clean"},
        augment_user_input_with_runtime_feedback=lambda planner_user_input, _latest: planner_user_input,
        fail_task_for_missing_clarification=lambda *_args, **_kwargs: calls.append("should_not_clarify"),
        start_task_execution=lambda _cur, task_id, planner_user_input: calls.append(("start", task_id, planner_user_input)),
        set_current_trace_context=lambda **kwargs: calls.append(("trace", kwargs["task_id"])),
        clear_current_trace_context=lambda: calls.append("clear_trace"),
        select_task_plan_source=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should use build_execution_plan_fn")),
        run_planned_execution=lambda _cur, task_id, planner_user_input, plan_selection, _claim, model_route_overrides: (
            calls.append(("run", task_id, planner_user_input, plan_selection["plan_source"], model_route_overrides["planner"]["provider"])),
            (["done"], {1: {"status": "completed"}}, {"result": "ok"}),
        )[1],
        finalize_task_success=lambda _cur, task_id, planner_user_input, step_outputs, step_context, var_context: calls.append(
            ("success", task_id, planner_user_input, step_outputs, step_context, var_context)
        ),
        finalize_task_failure=lambda *_args, **_kwargs: calls.append("should_not_fail"),
        maybe_dispatch_task_runtime_specialists=lambda *_args, **_kwargs: calls.append("should_not_dispatch"),
        approval_required_exc_type=RuntimeError,
        interrupt_requested_exc_type=InterruptedError,
        auto_recovery_scheduled_exc_type=ValueError,
        claim_lost_exc_type=KeyError,
        load_task_runtime_context_fn=lambda task: {
            "task": task,
            "task_id": task["id"],
            "user_input": task["user_input"],
            "task_intent": {"task_type": "research"},
            "deliverable_spec": {"deliverable_type": "research_summary", "clarify": {"blocking": False}},
            "model_route_overrides": {"planner": {"provider": "demo"}},
            "skill_invocation": {"skill_id": "demo_skill"},
        },
        build_intent_plan_fn=lambda context: {
            "task_type": context["task_intent"]["task_type"],
            "needs_clarification": False,
            "deliverable_type": context["deliverable_spec"]["deliverable_type"],
        },
        build_execution_plan_fn=lambda _cur, **kwargs: (
            calls.append(("execution_plan", kwargs["task_context"]["skill_invocation"]["skill_id"], kwargs["intent_plan"]["task_type"])),
            {"plan_source": "planner_v2", "steps": [{"step_order": 1}]},
        )[1],
    )

    assert ("execution_plan", "demo_skill", "research") in calls
    assert ("run", 35, "整理发布方案\n\n记忆补充", "planner_v2", "demo") in calls
    assert calls[-1][0] == "success"
