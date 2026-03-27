import pytest

from apps.worker.runtime.tools.input_resolution import (
    compare_values,
    get_nested_value,
    normalize_step_name,
    render_template_text,
    resolve_input_payload,
    resolve_reference_value,
    try_resolve_reference,
)


def test_normalize_step_name_strips_numbering():
    assert normalize_step_name("1. 第 1 步：整理结果") == "整理结果"


def test_get_nested_value_supports_dicts_and_lists():
    data = {"a": {"items": [{"name": "one"}, {"name": "two"}]}}
    assert get_nested_value(data, "a.items.1.name") == "two"


def test_resolve_reference_value_supports_step_and_var_context():
    step_context = {2: {"output_data": {"title": "done"}, "output_payload": "payload"}}
    var_context = {"region": "cn"}

    assert resolve_reference_value("step:2.data.title", step_context, var_context) == "done"
    assert resolve_reference_value("var:region", step_context, var_context) == "cn"


def test_resolve_input_payload_recurses_nested_payloads():
    step_context = {1: {"output_data": {"value": 7}, "output_payload": "payload"}}
    payload = {"left": "step:1.data.value", "items": ["var:missing", "step:1.output"]}

    with pytest.raises(ValueError):
        resolve_input_payload(payload, step_context, {})

    resolved = resolve_input_payload({"left": "step:1.data.value", "items": ["step:1.output"]}, step_context, {})
    assert resolved == {"left": 7, "items": ["payload"]}


def test_try_resolve_reference_swallows_resolution_errors():
    assert try_resolve_reference("var:missing", {}, {}) is None


def test_render_template_text_renders_structured_values():
    rendered = render_template_text(
        "标题={{ step.1.data.title }} 区域={{ var.region }}",
        {1: {"output_data": {"title": "发布说明"}, "output_payload": ""}},
        {"region": "cn"},
    )

    assert rendered == "标题=发布说明 区域=cn"


def test_compare_values_supports_supported_operators():
    assert compare_values("hello world", "contains", "world") is True
    assert compare_values(3, "gte", 2) is True
