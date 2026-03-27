from __future__ import annotations

import json
import re
from typing import Any


REFERENCE_PATTERN = re.compile(r"^step:(\d+)\.(data|output)(?:\.(.+))?$")
VAR_REFERENCE_PREFIX = "var:"
TEMPLATE_PATTERN = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


def normalize_step_name(step: str) -> str:
    step = (step or "").strip()
    step = re.sub(r"^\s*\d+[\.\)、:：-]\s*", "", step)
    step = re.sub(r"^\s*第\s*\d+\s*步[\s:：\-]*", "", step)
    return step.strip()


def get_nested_value(data: Any, path_str: str | None) -> Any:
    if path_str is None or path_str == "":
        return data

    current = data
    for part in path_str.split("."):
        if isinstance(current, dict):
            if part not in current:
                raise ValueError(f"引用路径不存在: {path_str}")
            current = current[part]
        elif isinstance(current, list):
            if not part.isdigit():
                raise ValueError(f"列表索引非法: {part}")
            idx = int(part)
            if idx < 0 or idx >= len(current):
                raise ValueError(f"列表索引越界: {part}")
            current = current[idx]
        else:
            raise ValueError(f"引用路径无法继续解析: {path_str}")
    return current


def resolve_reference_value(raw_value: Any, step_context: dict[int, dict], var_context: dict[str, Any] | None = None) -> Any:
    if not isinstance(raw_value, str):
        return raw_value

    raw_value = raw_value.strip()
    if raw_value.startswith(VAR_REFERENCE_PREFIX):
        var_name = raw_value[len(VAR_REFERENCE_PREFIX):].strip()
        if not var_name:
            raise ValueError("变量引用不能为空")
        if var_context is None or var_name not in var_context:
            raise ValueError(f"引用变量不存在: {raw_value}")
        return var_context[var_name]

    matched = REFERENCE_PATTERN.match(raw_value)
    if not matched:
        return raw_value

    ref_step_order = int(matched.group(1))
    ref_scope = matched.group(2)
    ref_path = matched.group(3)
    if ref_step_order not in step_context:
        raise ValueError(f"引用步骤不存在: {raw_value}")

    ref_step = step_context[ref_step_order]
    base = ref_step.get("output_data") if ref_scope == "data" else ref_step.get("output_payload")
    return get_nested_value(base, ref_path)


def resolve_input_payload(payload: Any, step_context: dict[int, dict], var_context: dict[str, Any] | None = None) -> Any:
    if isinstance(payload, dict):
        return {key: resolve_input_payload(value, step_context, var_context) for key, value in payload.items()}
    if isinstance(payload, list):
        return [resolve_input_payload(value, step_context, var_context) for value in payload]
    return resolve_reference_value(payload, step_context, var_context)


def try_resolve_reference(value: Any, step_context: dict[int, dict], var_context: dict[str, Any] | None = None) -> Any:
    try:
        return resolve_input_payload(value, step_context, var_context)
    except Exception:
        return None


def resolve_template_expr(expr: str, step_context: dict[int, dict], var_context: dict[str, Any] | None = None) -> Any:
    expr = (expr or "").strip()
    if not expr:
        raise ValueError("模板表达式不能为空")

    if expr.startswith("var."):
        var_name = expr[4:].strip()
        if not var_name:
            raise ValueError("模板变量名不能为空")
        if var_context is None or var_name not in var_context:
            raise ValueError(f"模板变量不存在: {expr}")
        return var_context[var_name]

    if expr.startswith("step."):
        parts = expr.split(".")
        if len(parts) < 3:
            raise ValueError(f"非法模板步骤引用: {expr}")
        step_order = parts[1]
        scope = parts[2]
        tail = ".".join(parts[3:]) if len(parts) > 3 else ""
        return resolve_reference_value(f"step:{step_order}.{scope}" + (f".{tail}" if tail else ""), step_context, var_context)

    return expr


def render_template_text(
    template: str,
    step_context: dict[int, dict],
    var_context: dict[str, Any] | None = None,
    strict: bool = True,
) -> str:
    def repl(match: re.Match) -> str:
        expr = match.group(1)
        try:
            value = resolve_template_expr(expr, step_context, var_context)
        except Exception:
            if strict:
                raise
            return match.group(0)
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    return TEMPLATE_PATTERN.sub(repl, template)


def compare_values(left: Any, operator: str, right: Any) -> bool:
    if operator == "eq":
        return left == right
    if operator == "ne":
        return left != right
    if operator == "gt":
        return left > right
    if operator == "lt":
        return left < right
    if operator == "gte":
        return left >= right
    if operator == "lte":
        return left <= right
    if operator == "contains":
        if isinstance(left, str):
            return str(right) in left
        if isinstance(left, list):
            return right in left
        if isinstance(left, dict):
            return str(right) in left
        raise ValueError(f"contains 不支持的 left 类型: {type(left).__name__}")
    if operator == "exists":
        return left is not None
    if operator == "not_exists":
        return left is None
    raise ValueError(f"不支持的 operator: {operator}")


__all__ = [
    "compare_values",
    "get_nested_value",
    "normalize_step_name",
    "render_template_text",
    "resolve_input_payload",
    "resolve_reference_value",
    "resolve_template_expr",
    "try_resolve_reference",
]
