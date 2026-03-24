from planner_runtime import (
    call_deepseek_planner,
    call_planner_with_retries,
    fallback_legacy_steps,
    plan_task,
    resolve_task_plan_source,
)


class FakeChoice:
    def __init__(self, content):
        self.message = type("Message", (), {"content": content})()


class FakeCompletion:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]


class FakeChatCompletions:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeCompletion(self.content)


class FakeClient:
    def __init__(self, content):
        self.chat = type("Chat", (), {"completions": FakeChatCompletions(content)})()


class FakeLogger:
    def __init__(self):
        self.warnings = []

    def warning(self, message, *args):
        self.warnings.append(message % args if args else message)


def test_call_deepseek_planner_normalizes_structured_steps():
    traces = []
    client = FakeClient(
        '{"steps":[{"step_order":2,"title":"查资料","tool":"web_search","input":{"query":"AI"},"error_strategy":"continue"}]}'
    )

    planned = call_deepseek_planner(
        "帮我规划一下",
        get_model_route_config=lambda _name, route_overrides=None: {
            "provider": "deepseek",
            "model_name": "planner-model",
            "temperature": 0.1,
            "max_tokens": 512,
        },
        get_model_provider_client=lambda _provider: client,
        record_model_trace=lambda **kwargs: traces.append(kwargs),
        serialize_model_route_runtime_info=lambda route_name, route: {"route_name": route_name, "model": route["model_name"]},
        normalize_step_name=lambda value: value.strip(),
        default_max_retries_for_tool=lambda tool_name: 2 if tool_name == "web_search" else 0,
        validate_planned_steps=lambda steps: steps,
        step_request_protocol_version="stage2-v1",
    )

    assert planned == [
        {
            "step_order": 2,
            "title": "查资料",
            "tool": "web_search",
            "input": {"query": "AI"},
            "run_if": None,
            "skip_if": None,
            "max_retries": 2,
            "error_strategy": "continue",
        }
    ]
    assert traces[0]["status"] == "completed"


def test_resolve_task_plan_source_falls_back_to_legacy_when_planner_fails():
    logger = FakeLogger()

    planned, source = resolve_task_plan_source(
        "帮我生成计划",
        infer_structured_steps_from_user_input=lambda _user_input: [],
        call_planner_with_retries_fn=lambda _user_input, model_route_overrides=None: (_ for _ in ()).throw(RuntimeError("planner down")),
        fallback_legacy_steps=lambda _user_input: ["拆解任务", "执行任务"],
        logger=logger,
    )

    assert planned == ["拆解任务", "执行任务"]
    assert source == "fallback_legacy"
    assert "planner fallback due to" in logger.warnings[0]


def test_call_planner_with_retries_retries_until_success():
    attempts = {"count": 0}

    def flaky(_user_input, model_route_overrides=None):
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise RuntimeError("transient")
        return [{"step_order": 1, "title": "ok"}]

    planned = call_planner_with_retries(
        "帮我规划",
        attempts=2,
        call_deepseek_planner_fn=flaky,
        sleep_seconds=0,
    )

    assert planned == [{"step_order": 1, "title": "ok"}]
    assert attempts["count"] == 2


def test_plan_task_returns_planned_steps_only():
    planned = plan_task(
        "帮我规划",
        resolve_task_plan_source_fn=lambda _user_input, model_route_overrides=None: ([{"step_order": 1}], "model"),
    )

    assert planned == [{"step_order": 1}]


def test_fallback_legacy_steps_prefers_workspace_write_flow():
    steps = fallback_legacy_steps("请读取 /workspace/demo.txt 并写入 /workspace/output.md")

    assert steps == ["读取文件内容", "整理文件要点", "写入摘要到文件"]
