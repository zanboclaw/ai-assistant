from step_request_runtime import (
    enrich_step_execution_request,
    normalize_step_execution_request,
    validate_planned_steps,
)


def test_normalize_step_execution_request_uses_default_retry_resolver():
    request = normalize_step_execution_request(
        {
            "step_order": 3,
            "tool": "generate_text",
            "input": {"prompt": "写一段总结"},
        },
        default_max_retries_for_tool=lambda tool_name: 2 if tool_name == "generate_text" else 0,
    )

    assert request["tool_name"] == "generate_text"
    assert request["max_retries"] == 2
    assert request["retry_count"] == 0


def test_enrich_step_execution_request_normalizes_web_search_and_marks_approval():
    execution_request = normalize_step_execution_request(
        {
            "step_order": 1,
            "tool": "web_search",
            "input": {"q": "帮我找几个小红书文案\n\n可复用的长期记忆：\n1. 历史经验"},
        },
        default_max_retries_for_tool=lambda _tool_name: 1,
    )

    enriched = enrich_step_execution_request(
        execution_request,
        {
            "step_order": 1,
            "tool": "web_search",
            "input": {"q": "帮我找几个小红书文案\n\n可复用的长期记忆：\n1. 历史经验"},
        },
        step_context={},
        var_context={},
        resolve_input_payload=lambda value, _step_context, _var_context: value,
        resolve_structured_step_input=lambda _tool_name, raw_input, _step_context, _var_context: dict(raw_input),
        normalize_web_search_input_fn=lambda payload: {"query": "帮我找几个小红书文案"},
        normalize_http_request_input_fn=lambda payload: payload,
        validate_input_value_fn=lambda tool_name, payload: payload["query"] if tool_name == "web_search" else None,
        should_require_approval=lambda tool_name, payload: (tool_name == "web_search", f"approval:{payload['query']}"),
    )

    assert enriched["should_run"] is True
    assert enriched["resolved_input"]["query"] == "帮我找几个小红书文案"
    assert enriched["approval_required"] is True
    assert enriched["approval_reason"] == "approval:帮我找几个小红书文案"


def test_validate_planned_steps_blocks_illegal_web_search_json_reference():
    try:
        validate_planned_steps(
            [
                {
                    "step_order": 1,
                    "tool": "web_search",
                    "input": {"query": "发布回滚 checklist"},
                },
                {
                    "step_order": 2,
                    "tool": "json_extract",
                    "input": {"data": "step:1.data.results", "path": "0.title"},
                },
            ],
            normalize_web_search_input_fn=lambda payload: payload,
        )
    except ValueError as exc:
        assert "planner 非法" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected validate_planned_steps to reject illegal web_search reference")
