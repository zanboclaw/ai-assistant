from __future__ import annotations

import json
import time
from typing import Any


PLANNER_SYSTEM_PROMPT = """
你是一个任务规划器。
你必须优先返回结构化 JSON 协议，不要输出解释文字。

返回格式必须是以下两种之一：

1. 推荐格式（结构化协议）：
{
  "steps": [
    {
      "step_order": 1,
      "title": "步骤标题",
      "tool": "file_read",
      "input": {"path": "/workspace/test.txt"},
      "error_strategy": "fail"
    }
  ]
}

2. 兼容格式（仅当你实在无法结构化时）：
{
  "steps": ["步骤1", "步骤2", "步骤3"]
}

支持工具只有：
- file_read
- file_write
- list_dir
- shell_exec
- generate_text
- summarize_text
- web_search
- read_json
- write_json
- http_request
- json_extract
- if_condition
- set_var
- template_render

规则：
- 读取文本文件用 file_read
- 写文本文件用 file_write
- 列目录用 list_dir
- 执行命令用 shell_exec
- 生成最终成品文本用 generate_text
- 整理总结文本用 summarize_text
- 网络搜索用 web_search
- 读取 JSON 文件用 read_json
- 写 JSON 文件用 write_json
- 请求 HTTP 接口用 http_request
- 从 JSON 对象中提取字段用 json_extract
- 条件判断用 if_condition
- 保存变量用 set_var
- 模板渲染用 template_render

http_request.input 只允许这些字段：
- url
- method
- params
- json
- timeout

如果是 POST 提交 JSON 数据，必须使用 json 字段。
绝对不要使用 data 字段。
http_request.timeout 必须是 1 到 20 之间的整数，如无必要统一使用 15。

json_extract.input 只允许这些字段：
- data
- path

json_extract.path 使用点路径格式，例如：
- planner
- modules.0
- args.q

web_search.input 只允许这些字段：
- query

web_search 必须使用 query 字段。
绝对不要使用 q 字段。

generate_text.input 只允许这些字段：
- prompt
- system_prompt

if_condition.input 支持两种格式：
- 单条件：left / operator / right
- 组合条件：logic / conditions

if_condition.logic 只支持：
- and
- or
- not

if_condition.conditions 是条件数组，数组里的每一项都必须是 left / operator / right。

if_condition.operator 只支持：
- eq
- ne
- gt
- lt
- gte
- lte
- contains
- exists
- not_exists

步骤可选控制字段：
- run_if
- skip_if

run_if / skip_if 使用布尔引用，例如：
- step:2.data.matched

set_var.input 只允许这些字段：
- name
- value

变量引用规则：
- 可使用 var:name 引用变量值

template_render.input 只允许这些字段：
- template
- strict

template_render 模板占位符只支持：
- {{step.N.data.xxx}}
- {{step.N.output}}
- {{var.name}}

引用规则：
- 可以在后续 step.input 中引用前面步骤输出
- 引用格式为：step:N.data.xxx
- 文本摘要常用：step:N.data.content 或 step:N.data.text
- JSON 常用：step:N.data.json
- HTTP 返回常用：step:N.data.json / step:N.data.text / step:N.data.status_code
- json_extract 结果常用：step:N.data.value
- web_search 结果只允许引用：
  - step:N.data.text
  - step:N.data.query
  - step:N.output
- 不允许把 web_search 输出当成 JSON 继续引用
- 不允许出现 step:N.data.json 或 step:N.data.results.* 指向 web_search 步骤

强约束：
- 只返回 JSON
- 不要 Markdown
- 不要代码块
- 不要额外解释
"""


def fallback_legacy_steps(user_input: str) -> list[str]:
    if "写入" in user_input and "/workspace/" in user_input:
        return ["读取文件内容", "整理文件要点", "写入摘要到文件"]
    if "读取文件" in user_input:
        return ["读取文件内容", "分析文件内容", "整理并输出结果"]
    if "列出目录" in user_input:
        return ["列出目录内容", "查看目录文件的关键信息", "整理关键内容并总结"]
    if "执行命令" in user_input or "shell" in user_input or "终端" in user_input:
        return ["执行命令", "读取命令输出内容", "整理输出内容"]
    if "调研" in user_input or "搜索" in user_input or "请求" in user_input or "接口" in user_input:
        return ["搜索资料", "整理方案", "对比分析", "制定可执行步骤"]
    return ["明确任务目标", "整理关键信息", "输出结果"]


def call_deepseek_planner(
    user_input: str,
    *,
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
    get_model_route_config,
    get_model_provider_client,
    record_model_trace,
    serialize_model_route_runtime_info,
    normalize_step_name,
    default_max_retries_for_tool,
    validate_planned_steps,
    step_request_protocol_version: str,
) -> list[dict] | list[str]:
    route = get_model_route_config("planner", route_overrides=model_route_overrides)
    client = get_model_provider_client(str(route["provider"]))
    prompt_text = f"[system]\n{PLANNER_SYSTEM_PROMPT}\n\n[user]\n{user_input}"
    content = ""
    try:
        completion = client.chat.completions.create(
            model=str(route["model_name"]),
            messages=[
                {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": user_input},
            ],
            response_format={"type": "json_object"},
            temperature=float(route["temperature"]),
            max_tokens=int(route["max_tokens"]),
        )

        content = (completion.choices[0].message.content or "").strip()
        if not content:
            raise ValueError("DeepSeek 返回空内容")
        record_model_trace(
            route_name="planner",
            provider=str(route["provider"]),
            model_name=str(route["model_name"]),
            prompt_version=step_request_protocol_version,
            prompt_text=prompt_text,
            response_text=content,
            status="completed",
            metadata=serialize_model_route_runtime_info("planner", route),
        )
    except Exception as exc:
        record_model_trace(
            route_name="planner",
            provider=str(route["provider"]),
            model_name=str(route["model_name"]),
            prompt_version=step_request_protocol_version,
            prompt_text=prompt_text,
            response_text=content,
            status="failed",
            error_summary=str(exc),
            metadata=serialize_model_route_runtime_info("planner", route),
        )
        raise

    data = json.loads(content)
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("planner 返回 steps 非法")

    if all(isinstance(x, str) for x in steps):
        return [normalize_step_name(x) for x in steps if str(x).strip()]

    normalized = []
    for i, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            continue
        tool_name = str(step.get("tool") or "").strip()
        normalized.append(
            {
                "step_order": int(step.get("step_order") or i),
                "title": str(step.get("title") or f"步骤 {i}"),
                "tool": tool_name,
                "input": step.get("input") or {},
                "run_if": step.get("run_if"),
                "skip_if": step.get("skip_if"),
                "max_retries": int(step.get("max_retries") or default_max_retries_for_tool(tool_name)),
                "error_strategy": str(step.get("error_strategy") or "fail"),
            }
        )

    if not normalized:
        raise ValueError("planner 返回的结构化步骤为空")

    return validate_planned_steps(normalized)


def call_planner_with_retries(
    user_input: str,
    attempts: int = 2,
    *,
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
    call_deepseek_planner_fn,
    sleep_seconds: float = 1.0,
) -> list[dict] | list[str]:
    last_error = None
    for _ in range(attempts):
        try:
            return call_deepseek_planner_fn(user_input, model_route_overrides=model_route_overrides)
        except Exception as exc:
            last_error = exc
            time.sleep(sleep_seconds)
    raise RuntimeError(f"planner failed after {attempts} attempts: {last_error}")


def resolve_task_plan_source(
    user_input: str,
    *,
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
    infer_structured_steps_from_user_input,
    call_planner_with_retries_fn,
    fallback_legacy_steps,
    logger,
) -> tuple[list[dict] | list[str], str]:
    inferred = infer_structured_steps_from_user_input(user_input)
    if inferred:
        return inferred, "inference"

    try:
        return call_planner_with_retries_fn(user_input, model_route_overrides=model_route_overrides), "model"
    except Exception as exc:
        logger.warning("planner fallback due to: %s", exc)
        return fallback_legacy_steps(user_input), "fallback_legacy"


def plan_task(
    user_input: str,
    *,
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
    resolve_task_plan_source_fn,
) -> list[dict] | list[str]:
    planned, _source = resolve_task_plan_source_fn(user_input, model_route_overrides=model_route_overrides)
    return planned
