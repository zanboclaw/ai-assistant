from pathlib import Path

from local_tool_runtime import (
    tool_file_read,
    tool_file_write,
    tool_if_condition,
    tool_if_condition_group,
    tool_json_extract,
    tool_list_dir,
    tool_read_json,
    tool_set_var,
    tool_template_render,
    tool_write_json,
)


def test_tool_file_write_and_read_round_trip(tmp_path: Path):
    target = tmp_path / "demo.txt"

    write_result = tool_file_write(
        str(target),
        "hello",
        ensure_writable_file=lambda path_str: Path(path_str),
    )
    read_result = tool_file_read(
        str(target),
        ensure_readable_file=lambda path_str: Path(path_str),
    )

    assert write_result["ok"] is True
    assert read_result["ok"] is True
    assert read_result["output_data"]["raw_text"] == "hello"


def test_tool_list_dir_sorts_directories_before_files(tmp_path: Path):
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "a-dir").mkdir()

    result = tool_list_dir(
        str(tmp_path),
        ensure_readable_dir=lambda path_str: Path(path_str),
    )

    assert result["ok"] is True
    assert result["output_data"]["entries"] == ["[DIR] a-dir", "[FILE] b.txt"]


def test_tool_read_write_json_and_extract_value(tmp_path: Path):
    target = tmp_path / "data.json"

    write_result = tool_write_json(
        str(target),
        {"planner": {"model": "deepseek"}},
        ensure_writable_file=lambda path_str: Path(path_str),
    )
    read_result = tool_read_json(
        str(target),
        ensure_readable_file=lambda path_str: Path(path_str),
    )
    extract_result = tool_json_extract(
        {"planner": {"model": "deepseek"}},
        "planner.model",
        get_nested_value=lambda data, path: data["planner"]["model"] if path == "planner.model" else None,
    )

    assert write_result["ok"] is True
    assert read_result["output_data"]["json"]["planner"]["model"] == "deepseek"
    assert extract_result["output_data"]["value"] == "deepseek"


def test_template_and_condition_tools_return_structured_outputs():
    rendered = tool_template_render(
        "Hello {{var.name}}",
        {},
        {"name": "world"},
        render_template_text=lambda template, _steps, var_context, _strict: template.replace("{{var.name}}", str(var_context["name"])),
    )
    grouped = tool_if_condition_group(
        "and",
        [{"left": 3, "operator": "gt", "right": 1}],
        supported_logics={"and", "or", "not"},
        evaluate_single_condition_payload_fn=lambda payload: {
            "matched": payload["left"] > payload["right"],
            "left": payload["left"],
            "operator": payload["operator"],
            "right": payload["right"],
        },
        build_group_output_text_fn=lambda logic, matched, results: f"{logic}:{matched}:{len(results)}",
    )
    single = tool_if_condition(
        left=2,
        operator="eq",
        right=2,
        supported_operators={"eq"},
        tool_if_condition_group_fn=lambda **kwargs: kwargs,
        compare_values=lambda left, operator, right: left == right if operator == "eq" else False,
    )

    assert rendered["output_data"]["rendered_text"] == "Hello world"
    assert grouped["output_data"]["matched"] is True
    assert single["output_data"]["matched"] is True


def test_tool_set_var_returns_value_payload():
    result = tool_set_var("topic", "agent")

    assert result["ok"] is True
    assert result["output_data"] == {"name": "topic", "value": "agent"}
