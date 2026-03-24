from __future__ import annotations

import re
from typing import Any, Callable, Optional, TypedDict

try:
    from typing import NotRequired
except ImportError:  # pragma: no cover - python<3.11 compatibility
    from typing_extensions import NotRequired


STEP_EXECUTION_REQUEST_FIELDS = (
    "step_order",
    "current_status",
    "tool_name",
    "raw_input",
    "run_if",
    "skip_if",
    "error_strategy",
    "max_retries",
    "retry_count",
)
ENRICHED_STEP_EXECUTION_REQUEST_EXTRA_FIELDS = (
    "should_run",
    "skip_reason",
    "resolved_input",
    "approval_required",
    "approval_reason",
    "effective_retry_count",
    "effective_max_retries",
    "result",
)


class StepExecutionRequest(TypedDict):
    step_order: int
    current_status: str
    tool_name: str
    raw_input: Any
    run_if: Any
    skip_if: Any
    error_strategy: str
    max_retries: int
    retry_count: int


class EnrichedStepExecutionRequest(StepExecutionRequest):
    should_run: bool
    skip_reason: str
    resolved_input: Any
    approval_required: bool
    approval_reason: str
    effective_retry_count: int
    effective_max_retries: int
    result: NotRequired[dict]


def should_run_step(
    step: dict,
    step_context: dict[int, dict],
    var_context: Optional[dict[str, Any]],
    *,
    resolve_input_payload: Callable[[Any, dict[int, dict], Optional[dict[str, Any]]], Any],
) -> tuple[bool, str]:
    run_if = step.get("run_if")
    skip_if = step.get("skip_if")

    if run_if is not None:
        value = resolve_input_payload(run_if, step_context, var_context)
        if not isinstance(value, bool):
            raise ValueError(f"run_if 解析结果不是布尔值: {value}")
        if not value:
            return False, "run_if 条件不满足"

    if skip_if is not None:
        value = resolve_input_payload(skip_if, step_context, var_context)
        if not isinstance(value, bool):
            raise ValueError(f"skip_if 解析结果不是布尔值: {value}")
        if value:
            return False, "skip_if 条件满足，跳过"

    return True, ""


def normalize_http_request_input(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return payload

    normalized = dict(payload)

    if "data" in normalized and "json" not in normalized:
        normalized["json"] = normalized.pop("data")

    timeout = normalized.get("timeout", 15)
    if not isinstance(timeout, int):
        timeout = 15
    if timeout < 1:
        timeout = 1
    if timeout > 20:
        timeout = 20
    normalized["timeout"] = timeout

    return normalized


def normalize_web_search_input(
    payload: dict,
    *,
    sanitize_web_search_query: Callable[[str], str],
) -> dict:
    if not isinstance(payload, dict):
        return payload

    normalized = dict(payload)
    if "query" not in normalized and isinstance(normalized.get("q"), str):
        normalized["query"] = normalized.pop("q")
    if isinstance(normalized.get("query"), str):
        normalized["query"] = sanitize_web_search_query(normalized.get("query") or "")
    return normalized


def iter_reference_strings(value: Any):
    if isinstance(value, str) and value.startswith("step:"):
        yield value
        return
    if isinstance(value, dict):
        for nested in value.values():
            yield from iter_reference_strings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from iter_reference_strings(nested)


def validate_planned_steps(
    steps: list[dict],
    *,
    normalize_web_search_input_fn: Callable[[dict], dict],
) -> list[dict]:
    normalized_steps: list[dict] = []
    tool_by_order: dict[int, str] = {}

    for step in steps:
        normalized_step = dict(step)
        tool_name = str(normalized_step.get("tool") or "").strip()
        step_order = int(normalized_step.get("step_order") or len(normalized_steps) + 1)
        raw_input = normalized_step.get("input") or {}

        if tool_name == "web_search":
            raw_input = normalize_web_search_input_fn(raw_input)
            normalized_step["input"] = raw_input

        for ref in iter_reference_strings(raw_input):
            match = re.match(r"step:(\d+)\.(.+)", ref)
            if not match:
                continue
            ref_step_order = int(match.group(1))
            ref_path = match.group(2)
            producer_tool = tool_by_order.get(ref_step_order, "")
            if producer_tool == "web_search":
                if ref_path.startswith("data.json") or ref_path.startswith("data.results"):
                    raise ValueError(
                        f"planner 非法引用 web_search 输出: {ref}。"
                        "web_search 只允许引用 step:N.data.text、step:N.data.query 或 step:N.output"
                    )
                if tool_name == "json_extract" and str(normalized_step.get("input", {}).get("data")) == ref:
                    raise ValueError(
                        f"planner 非法地把 web_search 结果当作 json_extract 输入: {ref}"
                    )

        normalized_steps.append(normalized_step)
        tool_by_order[step_order] = tool_name

    return normalized_steps


def validate_input_value(
    tool_name: str,
    payload: dict,
    *,
    tool_input_rules: dict[str, dict[str, set[str]]],
    get_tool_registry_entry: Callable[[str], dict[str, Any] | None],
    supported_operators: set[str],
    supported_logics: set[str],
):
    rules = tool_input_rules.get(tool_name)
    if not rules:
        config = get_tool_registry_entry(tool_name)
        if not config:
            raise ValueError(f"未知工具: {tool_name}")
        if str(config.get("provider_type") or "builtin").strip().lower() not in {"mcp_stdio", "mcp_http"}:
            raise ValueError(f"未知工具: {tool_name}")
        if not isinstance(payload, dict):
            raise ValueError(f"{tool_name} 的 input 必须是对象")
        return

    keys = set(payload.keys())
    missing = rules["required"] - keys
    if missing:
        raise ValueError(f"{tool_name} 缺少必填字段: {sorted(missing)}")

    unknown = keys - rules["required"] - rules["optional"]
    if unknown:
        raise ValueError(f"{tool_name} 存在非法字段: {sorted(unknown)}")

    if tool_name in {"file_read", "file_write", "list_dir", "read_json", "write_json"}:
        path_val = payload.get("path")
        if not isinstance(path_val, str) or not path_val.strip():
            raise ValueError(f"{tool_name} 的 path 非法")

    if tool_name == "file_write":
        if not isinstance(payload.get("content"), str):
            raise ValueError("file_write 的 content 必须是字符串")

    if tool_name == "shell_exec":
        if not isinstance(payload.get("command"), str) or not payload["command"].strip():
            raise ValueError("shell_exec 的 command 非法")

    if tool_name == "summarize_text":
        if not isinstance(payload.get("text"), str):
            raise ValueError("summarize_text 的 text 必须是字符串")

    if tool_name == "generate_text":
        if not isinstance(payload.get("prompt"), str) or not payload["prompt"].strip():
            raise ValueError("generate_text 的 prompt 必须是非空字符串")
        if "system_prompt" in payload and not isinstance(payload.get("system_prompt"), str):
            raise ValueError("generate_text 的 system_prompt 必须是字符串")

    if tool_name == "web_search":
        if not isinstance(payload.get("query"), str) or not payload["query"].strip():
            raise ValueError("web_search 的 query 非法")

    if tool_name == "write_json":
        data = payload.get("data")
        if not isinstance(data, (dict, list)):
            raise ValueError("write_json 的 data 必须是对象或数组")

    if tool_name == "http_request":
        url = payload.get("url")
        method = payload.get("method")
        timeout = payload.get("timeout", 15)

        if not isinstance(url, str) or not url.strip():
            raise ValueError("http_request 的 url 非法")

        if not isinstance(method, str) or method.upper().strip() not in {"GET", "POST"}:
            raise ValueError("http_request 的 method 仅支持 GET/POST")

        if not isinstance(timeout, int):
            raise ValueError("http_request 的 timeout 必须是整数")
        if timeout < 1 or timeout > 20:
            raise ValueError("http_request 的 timeout 必须在 1 到 20 之间")

        if "params" in payload and not isinstance(payload["params"], dict):
            raise ValueError("http_request 的 params 必须是对象")

        if "json" in payload and not isinstance(payload["json"], dict):
            raise ValueError("http_request 的 json 必须是对象")

    if tool_name == "json_extract":
        if not isinstance(payload.get("data"), (dict, list)):
            raise ValueError("json_extract 的 data 必须是对象或数组")
        if not isinstance(payload.get("path"), str) or not payload["path"].strip():
            raise ValueError("json_extract 的 path 必须是非空字符串")

    if tool_name == "if_condition":
        if not isinstance(payload, dict):
            raise ValueError("if_condition 的 input 必须是对象")

        has_single = all(k in payload for k in ["left", "operator", "right"])
        has_group = ("logic" in payload and "conditions" in payload)

        if has_single and has_group:
            raise ValueError("if_condition 不能同时使用单条件和组合条件格式")
        if not has_single and not has_group:
            raise ValueError("if_condition 必须提供 left/operator/right 或 logic/conditions")

        if has_single:
            operator = payload.get("operator")
            if not isinstance(operator, str) or operator not in supported_operators:
                raise ValueError(f"if_condition 的 operator 非法: {operator}")

        if has_group:
            logic = payload.get("logic")
            conditions = payload.get("conditions")
            if not isinstance(logic, str) or logic not in supported_logics:
                raise ValueError(f"if_condition 的 logic 非法: {logic}")
            if not isinstance(conditions, list) or not conditions:
                raise ValueError("if_condition 的 conditions 必须是非空数组")
            if logic == "not" and len(conditions) != 1:
                raise ValueError("logic=not 时 conditions 必须只有 1 条")
            for idx, condition in enumerate(conditions, start=1):
                if not isinstance(condition, dict):
                    raise ValueError(f"if_condition.conditions[{idx}] 必须是对象")
                if not all(k in condition for k in ["left", "operator", "right"]):
                    raise ValueError(f"if_condition.conditions[{idx}] 缺少 left/operator/right")
                operator = condition.get("operator")
                if not isinstance(operator, str) or operator not in supported_operators:
                    raise ValueError(f"if_condition.conditions[{idx}] 的 operator 非法: {operator}")


def normalize_step_execution_request(
    step: dict,
    *,
    default_max_retries_for_tool: Callable[[str], int],
) -> StepExecutionRequest:
    tool_name = str(step.get("tool") or "").strip()
    return {
        "step_order": int(step.get("step_order")),
        "current_status": str(step.get("status") or "pending"),
        "tool_name": tool_name,
        "raw_input": step.get("input") or {},
        "run_if": step.get("run_if"),
        "skip_if": step.get("skip_if"),
        "error_strategy": str(step.get("error_strategy") or "fail"),
        "max_retries": int(step.get("max_retries") or default_max_retries_for_tool(tool_name)),
        "retry_count": int(step.get("retry_count") or 0),
    }


def enrich_step_execution_request(
    execution_request: StepExecutionRequest,
    step: dict,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    *,
    resolve_input_payload: Callable[[Any, dict[int, dict], Optional[dict[str, Any]]], Any],
    resolve_structured_step_input: Callable[[str, Any, dict[int, dict], dict[str, Any]], Any],
    normalize_web_search_input_fn: Callable[[dict], dict],
    normalize_http_request_input_fn: Callable[[dict], dict],
    validate_input_value_fn: Callable[[str, dict], None],
    should_require_approval: Callable[[str, dict], tuple[bool, str]],
) -> EnrichedStepExecutionRequest:
    enriched = dict(execution_request)
    tool_name = str(enriched["tool_name"])
    raw_input = enriched["raw_input"]
    enriched["effective_retry_count"] = int(enriched["retry_count"])
    enriched["effective_max_retries"] = int(enriched["max_retries"])

    should_run, skip_reason = should_run_step(
        step,
        step_context,
        var_context,
        resolve_input_payload=resolve_input_payload,
    )
    enriched["should_run"] = should_run
    enriched["skip_reason"] = skip_reason

    if should_run:
        resolved_input = resolve_structured_step_input(tool_name, raw_input, step_context, var_context)
        if tool_name == "web_search":
            resolved_input = normalize_web_search_input_fn(resolved_input)
        if tool_name == "http_request":
            resolved_input = normalize_http_request_input_fn(resolved_input)
        validate_input_value_fn(tool_name, resolved_input)
        enriched["resolved_input"] = resolved_input
        approval_required, approval_reason = should_require_approval(tool_name, resolved_input)
        enriched["approval_required"] = approval_required
        enriched["approval_reason"] = approval_reason
    else:
        enriched["resolved_input"] = None
        enriched["approval_required"] = False
        enriched["approval_reason"] = ""

    return enriched
