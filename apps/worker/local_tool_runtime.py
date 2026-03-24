from __future__ import annotations

import json
from typing import Any


def tool_file_read(path_str: str, *, ensure_readable_file) -> dict:
    try:
        path = ensure_readable_file(path_str)
        content = path.read_text(encoding="utf-8")
        output_text = f"file_read 结果（{path_str}）：\n{content}"
        return {
            "ok": True,
            "output_text": output_text,
            "output_data": {
                "path": path_str,
                "content": output_text,
                "raw_text": content,
            },
            "error": "",
        }
    except Exception as exc:
        message = f"file_read 执行失败：{exc}"
        return {
            "ok": False,
            "output_text": message,
            "output_data": None,
            "error": message,
        }


def tool_file_write(path_str: str, content: str, *, ensure_writable_file) -> dict:
    try:
        path = ensure_writable_file(path_str)
        path.write_text(content, encoding="utf-8")
        output_text = f"file_write 成功：已写入文件 -> {path_str}"
        return {
            "ok": True,
            "output_text": output_text,
            "output_data": {"path": path_str},
            "error": "",
        }
    except Exception as exc:
        message = f"file_write 执行失败：{exc}"
        return {
            "ok": False,
            "output_text": message,
            "output_data": None,
            "error": message,
        }


def tool_list_dir(path_str: str, *, ensure_readable_dir) -> dict:
    try:
        path = ensure_readable_dir(path_str)
        items = []
        for entry in sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            prefix = "[DIR]" if entry.is_dir() else "[FILE]"
            items.append(f"{prefix} {entry.name}")

        output_text = f"list_dir 结果（{path_str}）：\n" + "\n".join(items)
        return {
            "ok": True,
            "output_text": output_text,
            "output_data": {
                "path": path_str,
                "entries": items,
            },
            "error": "",
        }
    except Exception as exc:
        message = f"list_dir 执行失败：{exc}"
        return {
            "ok": False,
            "output_text": message,
            "output_data": None,
            "error": message,
        }


def tool_read_json(path_str: str, *, ensure_readable_file, json_module=json) -> dict:
    try:
        path = ensure_readable_file(path_str)
        raw_text = path.read_text(encoding="utf-8")
        parsed = json_module.loads(raw_text)

        output_text = (
            f"read_json 成功：已读取 JSON 文件 -> {path_str}\n"
            f"JSON 类型：{'object' if isinstance(parsed, dict) else 'array' if isinstance(parsed, list) else type(parsed).__name__}"
        )
        return {
            "ok": True,
            "output_text": output_text,
            "output_data": {
                "path": path_str,
                "json": parsed,
                "raw_text": raw_text,
            },
            "error": "",
        }
    except Exception as exc:
        message = f"read_json 执行失败：{exc}"
        return {
            "ok": False,
            "output_text": message,
            "output_data": None,
            "error": message,
        }


def tool_write_json(path_str: str, data: Any, *, ensure_writable_file, json_module=json) -> dict:
    try:
        path = ensure_writable_file(path_str)
        text = json_module.dumps(data, ensure_ascii=False, indent=2)
        path.write_text(text, encoding="utf-8")
        output_text = f"write_json 成功：已写入 JSON 文件 -> {path_str}"
        return {
            "ok": True,
            "output_text": output_text,
            "output_data": {"path": path_str},
            "error": "",
        }
    except Exception as exc:
        message = f"write_json 执行失败：{exc}"
        return {
            "ok": False,
            "output_text": message,
            "output_data": None,
            "error": message,
        }


def tool_json_extract(data: Any, path: str, *, get_nested_value, json_module=json) -> dict:
    try:
        value = get_nested_value(data, path)
        preview = json_module.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
        output_text = f"json_extract 成功：path={path}\n提取结果：{preview}"
        return {
            "ok": True,
            "output_text": output_text,
            "output_data": {
                "path": path,
                "value": value,
            },
            "error": "",
        }
    except Exception as exc:
        message = f"json_extract 执行失败：{exc}"
        return {
            "ok": False,
            "output_text": message,
            "output_data": None,
            "error": message,
        }


def evaluate_single_condition_payload(payload: dict, *, compare_values) -> dict:
    operator = payload["operator"]
    left = payload.get("left")
    right = payload.get("right")
    matched = compare_values(left, operator, right)
    return {
        "matched": matched,
        "left": left,
        "operator": operator,
        "right": right,
    }


def tool_set_var(name: str, value: Any) -> dict:
    output_text = f"set_var 成功：{name}={value}"
    return {
        "ok": True,
        "output_text": output_text,
        "output_data": {
            "name": name,
            "value": value,
        },
        "error": "",
    }


def tool_template_render(
    template: str,
    step_context: dict[int, dict],
    var_context: dict[str, Any] | None = None,
    strict: bool = True,
    *,
    render_template_text,
) -> dict:
    try:
        rendered = render_template_text(template, step_context, var_context, strict)
        return {
            "ok": True,
            "output_text": f"template_render 成功：已渲染模板，长度={len(rendered)}",
            "output_data": {
                "rendered_text": rendered,
            },
            "error": "",
        }
    except Exception as exc:
        message = f"template_render 执行失败：{exc}"
        return {
            "ok": False,
            "output_text": message,
            "output_data": None,
            "error": message,
        }


def build_group_output_text(logic: str, matched: bool, results: list[dict]) -> str:
    detail_parts = []
    for index, result in enumerate(results, start=1):
        detail_parts.append(f"{index}:{'true' if result['matched'] else 'false'}({result['operator']})")
    details = ",".join(detail_parts)
    return (
        f"if_condition 成功：logic={logic} "
        f"result={'true' if matched else 'false'} "
        f"details=[{details}]"
    )


def tool_if_condition_group(
    logic: str,
    conditions: list[dict],
    *,
    supported_logics: set[str],
    evaluate_single_condition_payload_fn,
    build_group_output_text_fn,
) -> dict:
    try:
        if logic not in supported_logics:
            raise ValueError(f"不支持的 logic: {logic}")
        if not isinstance(conditions, list) or not conditions:
            raise ValueError("conditions 必须是非空数组")
        if logic == "not" and len(conditions) != 1:
            raise ValueError("logic=not 时 conditions 必须只有 1 条")

        results = [evaluate_single_condition_payload_fn(condition) for condition in conditions]
        if logic == "and":
            matched = all(item["matched"] for item in results)
        elif logic == "or":
            matched = any(item["matched"] for item in results)
        elif logic == "not":
            matched = not results[0]["matched"]
        else:
            raise ValueError(f"不支持的 logic: {logic}")

        return {
            "ok": True,
            "output_text": build_group_output_text_fn(logic, matched, results),
            "output_data": {
                "matched": matched,
                "logic": logic,
                "results": results,
            },
            "error": "",
        }
    except Exception as exc:
        message = f"if_condition 执行失败：{exc}"
        return {
            "ok": False,
            "output_text": message,
            "output_data": None,
            "error": message,
        }


def tool_if_condition(
    left: Any = None,
    operator: str | None = None,
    right: Any = None,
    logic: str | None = None,
    conditions: list[dict] | None = None,
    *,
    supported_operators: set[str],
    tool_if_condition_group_fn,
    compare_values,
) -> dict:
    if logic is not None or conditions is not None:
        return tool_if_condition_group_fn(logic=logic or "", conditions=conditions or [])

    try:
        if operator not in supported_operators:
            raise ValueError(f"不支持的 operator: {operator}")
        matched = compare_values(left, operator, right)
        output_text = (
            f"if_condition 成功：left={left} "
            f"operator={operator} right={right} "
            f"result={'true' if matched else 'false'}"
        )
        return {
            "ok": True,
            "output_text": output_text,
            "output_data": {
                "matched": matched,
                "left": left,
                "operator": operator,
                "right": right,
            },
            "error": "",
        }
    except Exception as exc:
        message = f"if_condition 执行失败：{exc}"
        return {
            "ok": False,
            "output_text": message,
            "output_data": None,
            "error": message,
        }
