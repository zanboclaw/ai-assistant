from apps.worker.runtime.execution.step_projection import (
    build_structured_steps_from_rows,
    hydrate_contexts_from_steps,
)


def test_build_structured_steps_from_rows_parses_runtime_fields():
    planned = build_structured_steps_from_rows(
        [
            {
                "id": 5,
                "step_order": 2,
                "step_name": "生成文案",
                "tool_name": "generate_text",
                "input_payload": '{"prompt":"hello"}',
                "run_if": '{"operator":"exists"}',
                "skip_if": None,
                "retry_count": 1,
                "max_retries": 2,
                "error_strategy": "continue",
                "status": "completed",
                "output_payload": "done",
                "output_data": '{"text":"done"}',
            }
        ],
        parse_json_text=lambda value, default=None: {"parsed": value} if value is not None else default,
    )

    assert planned == [
        {
            "id": 5,
            "step_order": 2,
            "title": "生成文案",
            "tool": "generate_text",
            "input": {"parsed": '{"prompt":"hello"}'},
            "run_if": {"parsed": '{"operator":"exists"}'},
            "skip_if": None,
            "retry_count": 1,
            "max_retries": 2,
            "error_strategy": "continue",
            "status": "completed",
            "output_payload": "done",
            "output_data": {"parsed": '{"text":"done"}'},
        }
    ]


def test_hydrate_contexts_from_steps_collects_outputs_and_vars():
    step_context, var_context, step_outputs = hydrate_contexts_from_steps(
        [
            {
                "step_order": 1,
                "tool": "web_search",
                "status": "completed",
                "output_payload": "search done",
                "output_data": {"items": 3},
            },
            {
                "step_order": 2,
                "tool": "set_var",
                "status": "completed",
                "output_payload": "region stored",
                "output_data": {"name": "region", "value": "cn"},
            },
            {
                "step_order": 3,
                "tool": "generate_text",
                "status": "pending",
                "output_payload": "ignored",
                "output_data": {"text": "ignored"},
            },
        ]
    )

    assert step_outputs == ["search done", "region stored"]
    assert step_context[1]["output_data"] == {"items": 3}
    assert step_context[2]["output_payload"] == "region stored"
    assert var_context == {"region": "cn"}
