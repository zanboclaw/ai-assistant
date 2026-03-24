import pytest

from structured_step_runtime import (
    begin_structured_step_execution,
    complete_structured_step_execution,
    execute_prepared_step_request,
    route_structured_step_outcome,
)


class FakeLogger:
    def __init__(self):
        self.messages = []

    def info(self, message, *args):
        self.messages.append(message % args if args else message)


class FakeHeartbeat:
    def __init__(self):
        self.asserted = 0

    def assert_owned(self):
        self.asserted += 1


def test_execute_prepared_step_request_records_skip_and_returns_existing_retry_count():
    skipped_calls = []

    result, retry_count = execute_prepared_step_request(
        cur=object(),
        task_id=12,
        user_input="写周报",
        step={"step_order": 2},
        execution_request={
            "step_order": 2,
            "tool_name": "generate_text",
            "raw_input": {"prompt": "写周报"},
            "run_if": {"eq": True},
            "skip_if": {"eq": False},
            "error_strategy": "stop",
            "should_run": False,
            "skip_reason": "前置条件未满足",
            "effective_max_retries": 3,
            "effective_retry_count": 2,
            "resolved_input": {"prompt": "写周报"},
            "approval_required": False,
            "approval_reason": "",
        },
        step_context={},
        var_context={},
        step_outputs=[],
        claim_heartbeat=None,
        model_route_overrides=None,
        record_skipped_step=lambda *args, **kwargs: skipped_calls.append((args, kwargs)),
        enforce_step_approval=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not approve")),
        execute_step_with_retries=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not run")),
        step_trace_id=31,
        tool_trace_id=32,
    )

    assert result is None
    assert retry_count == 2
    assert skipped_calls[0][1]["step_trace_id"] == 31
    assert skipped_calls[0][1]["tool_trace_id"] == 32


def test_route_structured_step_outcome_uses_continue_path_for_continue_on_error():
    logger = FakeLogger()
    continue_calls = []

    route_structured_step_outcome(
        cur=object(),
        task_id=99,
        user_input="执行失败也继续",
        execution_request={
            "step_order": 5,
            "tool_name": "http_request",
            "error_strategy": "continue",
            "resolved_input": {"url": "https://example.com"},
        },
        result={"ok": False, "error": "timeout", "output_text": "请求失败", "output_data": None},
        retry_count=1,
        step_context={},
        var_context={},
        step_outputs=[],
        logger=logger,
        finalize_structured_step_success=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("should not finalize success")
        ),
        finalize_structured_step_continue=lambda *args, **kwargs: continue_calls.append((args, kwargs)),
        step_trace_id=41,
        tool_trace_id=42,
    )

    assert continue_calls
    assert continue_calls[0][1]["step_trace_id"] == 41
    assert continue_calls[0][1]["tool_trace_id"] == 42
    assert "status=failed" in logger.messages[0]


def test_begin_structured_step_execution_creates_trace_and_sets_context():
    logger = FakeLogger()
    heartbeat = FakeHeartbeat()
    calls = []

    should_run, step_trace_id, tool_trace_id = begin_structured_step_execution(
        cur=object(),
        task_id=7,
        user_input="整理数据",
        step={"id": 18},
        execution_request={
            "step_order": 3,
            "tool_name": "web_search",
            "retry_count": 1,
            "max_retries": 4,
            "raw_input": {"query": "整理数据"},
            "current_status": "pending",
        },
        step_context={},
        var_context={},
        step_outputs=[],
        claim_heartbeat=heartbeat,
        logger=logger,
        get_task_control_status=lambda _task_id: "running",
        interrupt_task_if_requested=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("should not interrupt")
        ),
        start_step_execution=lambda _cur, task_id, step_order: calls.append(("start", task_id, step_order)),
        create_step_and_tool_trace=lambda _cur, **kwargs: (calls.append(("trace", kwargs)) or (81, 82)),
        set_current_trace_context=lambda **kwargs: calls.append(("context", kwargs)),
    )

    assert heartbeat.asserted == 1
    assert should_run is True
    assert (step_trace_id, tool_trace_id) == (81, 82)
    assert ("start", 7, 3) in calls
    assert any(item[0] == "context" and item[1]["step_trace_id"] == 81 for item in calls)


def test_complete_structured_step_execution_routes_success_with_updated_retry_count():
    route_calls = []

    complete_structured_step_execution(
        cur=object(),
        task_id=21,
        user_input="生成日报",
        step={"id": 9, "tool": "generate_text"},
        execution_request={
            "step_order": 2,
            "tool_name": "generate_text",
            "raw_input": {"prompt": "生成日报"},
            "error_strategy": "stop",
            "retry_count": 0,
            "max_retries": 2,
        },
        step_context={},
        var_context={},
        step_outputs=[],
        claim_heartbeat=None,
        model_route_overrides={"planner": {"provider": "demo"}},
        process_structured_step_request_fn=lambda *_args, **_kwargs: (
            {
                "step_order": 2,
                "tool_name": "generate_text",
                "resolved_input": {"prompt": "生成日报"},
                "error_strategy": "stop",
                "effective_retry_count": 1,
                "effective_max_retries": 2,
                "retry_count": 0,
                "max_retries": 2,
                "raw_input": {"prompt": "生成日报"},
            },
            {"ok": True, "output_text": "日报完成", "output_data": {"content": "日报完成"}},
            1,
        ),
        route_structured_step_outcome_fn=lambda *args, **kwargs: route_calls.append((args, kwargs)),
        record_structured_step_exception=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("should not record exception")
        ),
        complete_step_and_tool_trace=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("should not complete trace on success here")
        ),
        approval_required_exc_type=RuntimeError,
        step_trace_id=51,
        tool_trace_id=52,
    )

    assert route_calls
    route_args, route_kwargs = route_calls[0]
    assert route_args[3]["resolved_input"]["prompt"] == "生成日报"
    assert route_args[5] == 1
    assert route_kwargs["step_trace_id"] == 51
    assert route_kwargs["tool_trace_id"] == 52


def test_complete_structured_step_execution_records_exception_and_reraises():
    recorded_errors = []
    completed_traces = []

    with pytest.raises(ValueError, match="boom"):
        complete_structured_step_execution(
            cur=object(),
            task_id=31,
            user_input="导出报表",
            step={"id": 4},
            execution_request={
                "step_order": 6,
                "tool_name": "http_request",
                "raw_input": {"url": "https://example.com/report"},
                "error_strategy": "stop",
                "retry_count": 1,
                "max_retries": 4,
                "effective_retry_count": 1,
                "effective_max_retries": 4,
            },
            step_context={},
            var_context={},
            step_outputs=[],
            claim_heartbeat=None,
            model_route_overrides=None,
            process_structured_step_request_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("boom")),
            route_structured_step_outcome_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("should not route success")
            ),
            record_structured_step_exception=lambda *args: recorded_errors.append(args),
            complete_step_and_tool_trace=lambda *_args, **kwargs: completed_traces.append(kwargs),
            approval_required_exc_type=KeyError,
            step_trace_id=61,
            tool_trace_id=62,
        )

    assert recorded_errors
    assert "已重试 1/4 次" in recorded_errors[0][-1]
    assert completed_traces[0]["step_trace_id"] == 61
    assert completed_traces[0]["tool_trace_id"] == 62
    assert completed_traces[0]["retry_count"] == 1
    assert "已重试 1/4 次" in completed_traces[0]["error_summary"]
