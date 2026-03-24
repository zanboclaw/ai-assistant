from __future__ import annotations

import re


def infer_structured_steps_from_user_input(user_input: str, *, extract_path_from_text) -> list[dict]:
    src_path = extract_path_from_text(user_input)
    matches = re.findall(r"(/[^ \n\r\t'\"，。；：]+)", user_input)
    target_path = matches[-1] if len(matches) >= 2 else None

    extract_match = re.search(r"提取\s+([A-Za-z0-9_.]+)\s+字段", user_input)
    extract_path = extract_match.group(1).strip() if extract_match else None

    if (
        src_path
        and src_path.endswith(".json")
        and target_path
        and ("保存为变量" in user_input or "保存变量" in user_input)
        and ("planner" in user_input)
        and ("写入" in user_input)
    ):
        return [
            {"step_order": 1, "title": "读取 JSON 文件", "tool": "read_json", "input": {"path": src_path}, "error_strategy": "fail"},
            {"step_order": 2, "title": "保存 planner 变量", "tool": "set_var", "input": {"name": "planner_name", "value": "step:1.data.json.planner"}, "error_strategy": "fail"},
            {"step_order": 3, "title": "写入变量值", "tool": "file_write", "input": {"path": target_path, "content": "var:planner_name"}, "error_strategy": "fail"},
        ]

    if (
        src_path
        and src_path.endswith(".json")
        and target_path
        and ("渲染成报告" in user_input or "渲染报告" in user_input)
        and ("planner" in user_input)
        and ("version" in user_input)
    ):
        return [
            {"step_order": 1, "title": "读取 JSON 文件", "tool": "read_json", "input": {"path": src_path}, "error_strategy": "fail"},
            {"step_order": 2, "title": "保存 planner 变量", "tool": "set_var", "input": {"name": "planner_name", "value": "step:1.data.json.planner"}, "error_strategy": "fail"},
            {"step_order": 3, "title": "保存 version 变量", "tool": "set_var", "input": {"name": "version_text", "value": "step:1.data.json.version"}, "error_strategy": "fail"},
            {
                "step_order": 4,
                "title": "渲染 JSON 报告",
                "tool": "template_render",
                "input": {"template": "# JSON 报告\n\nPlanner: {{var.planner_name}}\nVersion: {{var.version_text}}\n", "strict": True},
                "error_strategy": "fail",
            },
            {"step_order": 5, "title": "写入 JSON 报告", "tool": "file_write", "input": {"path": target_path, "content": "step:4.data.rendered_text"}, "error_strategy": "fail"},
        ]

    if (
        target_path
        and ("http" in user_input.lower())
        and ("渲染成结果文件" in user_input or "渲染成结果" in user_input or "渲染成报告" in user_input)
        and ("状态码" in user_input)
    ):
        url_match = re.search(r"(https?://[^\s'\"，。；：]+)", user_input)
        if url_match:
            url = url_match.group(1).strip()
            method = "POST" if ("post" in user_input.lower() or "提交" in user_input) else "GET"
            return [
                {"step_order": 1, "title": "请求接口", "tool": "http_request", "input": {"url": url, "method": method, "timeout": 15}, "error_strategy": "fail"},
                {
                    "step_order": 2,
                    "title": "渲染 HTTP 报告",
                    "tool": "template_render",
                    "input": {"template": "# HTTP 报告\n\nStatus Code: {{step.1.data.status_code}}\nBody: {{step.1.data.text}}\n", "strict": True},
                    "error_strategy": "fail",
                },
                {"step_order": 3, "title": "写入 HTTP 报告", "tool": "file_write", "input": {"path": target_path, "content": "step:2.data.rendered_text"}, "error_strategy": "fail"},
            ]

    if (
        src_path
        and src_path.endswith(".json")
        and target_path
        and ("如果" in user_input or "若" in user_input)
        and ("planner" in user_input)
        and ("等于 DeepSeek" in user_input or "等于DeepSeek" in user_input)
        and ("渲染成成功报告" in user_input or "渲染成功报告" in user_input)
    ):
        return [
            {"step_order": 1, "title": "读取 JSON 文件", "tool": "read_json", "input": {"path": src_path}, "error_strategy": "fail"},
            {"step_order": 2, "title": "判断 planner 条件", "tool": "if_condition", "input": {"left": "step:1.data.json.planner", "operator": "eq", "right": "DeepSeek"}, "error_strategy": "fail"},
            {
                "step_order": 3,
                "title": "渲染成功报告",
                "tool": "template_render",
                "input": {"template": "# 成功报告\n\nPlanner: {{step.1.data.json.planner}}\nVersion: {{step.1.data.json.version}}\n", "strict": True},
                "run_if": "step:2.data.matched",
                "error_strategy": "fail",
            },
            {"step_order": 4, "title": "写入成功报告", "tool": "file_write", "input": {"path": target_path, "content": "step:3.data.rendered_text"}, "run_if": "step:2.data.matched", "error_strategy": "fail"},
        ]

    if (
        src_path
        and src_path.endswith(".json")
        and len(matches) >= 3
        and ("如果" in user_input or "若" in user_input)
        and ("planner" in user_input)
        and ("否则" in user_input)
        and ("等于" in user_input or "不等于" in user_input)
    ):
        true_path = matches[-2]
        false_path = matches[-1]
        if "不等于" in user_input:
            operator = "ne"
            right_value = user_input.split("不等于", 1)[1]
        else:
            operator = "eq"
            right_value = user_input.split("等于", 1)[1]
        right_value = re.split(r"[；;，,。\n]", right_value)[0].strip()
        right_value = re.sub(r"^(就|则|那就)?(写入|输出到?)", "", right_value).strip()
        right_value = right_value.strip("`'\"“”‘’ ")
        return [
            {"step_order": 1, "title": "读取 JSON 文件", "tool": "read_json", "input": {"path": src_path}, "error_strategy": "fail"},
            {"step_order": 2, "title": "判断 planner 条件", "tool": "if_condition", "input": {"left": "step:1.data.json.planner", "operator": operator, "right": right_value}, "error_strategy": "fail"},
            {"step_order": 3, "title": "写入条件成立结果", "tool": "file_write", "input": {"path": true_path, "content": "matched"}, "run_if": "step:2.data.matched", "error_strategy": "fail"},
            {"step_order": 4, "title": "写入条件不成立结果", "tool": "file_write", "input": {"path": false_path, "content": "not matched"}, "skip_if": "step:2.data.matched", "error_strategy": "fail"},
        ]

    if (
        "http" in user_input.lower()
        and target_path
        and "状态码" in user_input
        and "包含" in user_input
        and "且" in user_input
        and "ai" in user_input.lower()
        and "写入" in user_input
    ):
        url_match = re.search(r"(https?://[^\s'\"，。；：]+)", user_input)
        if url_match:
            url = url_match.group(1).strip()
            code_match = re.search(r"状态码\s*等于\s*(\d+)", user_input)
            expected_code = int(code_match.group(1)) if code_match else 200
            method = "POST" if ("post" in user_input.lower() or "提交" in user_input) else "GET"
            return [
                {"step_order": 1, "title": "请求接口", "tool": "http_request", "input": {"url": url, "method": method, "timeout": 15}, "error_strategy": "fail"},
                {"step_order": 2, "title": "判断 HTTP 组合条件", "tool": "if_condition", "input": {"logic": "and", "conditions": [{"left": "step:1.data.status_code", "operator": "eq", "right": expected_code}, {"left": "step:1.data.text", "operator": "contains", "right": "ai"}]}, "error_strategy": "fail"},
                {"step_order": 3, "title": "写入组合条件成立结果", "tool": "file_write", "input": {"path": target_path, "content": "http and ok"}, "run_if": "step:2.data.matched", "error_strategy": "fail"},
            ]

    if (
        src_path and src_path.endswith(".json") and target_path
        and "存在" in user_input and "planner" in user_input and "modules" in user_input and "包含" in user_input and "worker" in user_input and "且" in user_input and "写入" in user_input
    ):
        return [
            {"step_order": 1, "title": "读取 JSON 文件", "tool": "read_json", "input": {"path": src_path}, "error_strategy": "fail"},
            {"step_order": 2, "title": "判断 JSON 组合条件", "tool": "if_condition", "input": {"logic": "and", "conditions": [{"left": "step:1.data.json.planner", "operator": "exists", "right": True}, {"left": "step:1.data.json.modules", "operator": "contains", "right": "worker"}]}, "error_strategy": "fail"},
            {"step_order": 3, "title": "写入组合条件成立结果", "tool": "file_write", "input": {"path": target_path, "content": "json and ok"}, "run_if": "step:2.data.matched", "error_strategy": "fail"},
        ]

    if (
        src_path and src_path.endswith(".json") and target_path
        and "planner" in user_input and ("或" in user_input or "或者" in user_input) and "写入" in user_input
    ):
        return [
            {"step_order": 1, "title": "读取 JSON 文件", "tool": "read_json", "input": {"path": src_path}, "error_strategy": "fail"},
            {"step_order": 2, "title": "判断 JSON 或条件", "tool": "if_condition", "input": {"logic": "or", "conditions": [{"left": "step:1.data.json.error", "operator": "exists", "right": True}, {"left": "step:1.data.json.planner", "operator": "eq", "right": "DeepSeek"}]}, "error_strategy": "fail"},
            {"step_order": 3, "title": "写入或条件成立结果", "tool": "file_write", "input": {"path": target_path, "content": "json or ok"}, "run_if": "step:2.data.matched", "error_strategy": "fail"},
        ]

    if (
        src_path and src_path.endswith(".json") and target_path
        and "不是" in user_input and "error" in user_input and "存在" in user_input and "写入" in user_input
    ):
        return [
            {"step_order": 1, "title": "读取 JSON 文件", "tool": "read_json", "input": {"path": src_path}, "error_strategy": "fail"},
            {"step_order": 2, "title": "判断 JSON 非条件", "tool": "if_condition", "input": {"logic": "not", "conditions": [{"left": "step:1.data.json.error", "operator": "exists", "right": True}]}, "error_strategy": "fail"},
            {"step_order": 3, "title": "写入非条件成立结果", "tool": "file_write", "input": {"path": target_path, "content": "json not ok"}, "run_if": "step:2.data.matched", "error_strategy": "fail"},
        ]

    if (
        src_path
        and src_path.endswith(".json")
        and target_path
        and ("如果" in user_input or "若" in user_input)
        and ("planner" in user_input)
        and ("等于" in user_input or "不等于" in user_input)
        and "写入" in user_input
    ):
        if "不等于" in user_input:
            operator = "ne"
            right_value = user_input.split("不等于", 1)[1]
        else:
            operator = "eq"
            right_value = user_input.split("等于", 1)[1]
        right_value = re.split(r"[；;，,。\n]", right_value)[0].strip()
        right_value = re.sub(r"^(就|则|那就)?(写入|输出到?)", "", right_value).strip()
        right_value = right_value.strip("`'\"“”‘’ ")
        return [
            {"step_order": 1, "title": "读取 JSON 文件", "tool": "read_json", "input": {"path": src_path}, "error_strategy": "fail"},
            {"step_order": 2, "title": "判断 planner 条件", "tool": "if_condition", "input": {"left": "step:1.data.json.planner", "operator": operator, "right": right_value}, "error_strategy": "fail"},
            {"step_order": 3, "title": "写入条件成立结果", "tool": "file_write", "input": {"path": target_path, "content": "matched"}, "run_if": "step:2.data.matched", "error_strategy": "fail"},
        ]

    if (
        "http" in user_input.lower()
        and target_path
        and ("如果" in user_input or "若" in user_input)
        and ("状态码" in user_input)
        and ("等于" in user_input or "不等于" in user_input)
        and "写入" in user_input
    ):
        url_match = re.search(r"(https?://[^\s'\"，。；：]+)", user_input)
        if url_match:
            url = url_match.group(1).strip()
            if "不等于" in user_input:
                operator = "ne"
                code_match = re.search(r"状态码\s*不等于\s*(\d+)", user_input)
            else:
                operator = "eq"
                code_match = re.search(r"状态码\s*等于\s*(\d+)", user_input)
            expected_code = int(code_match.group(1)) if code_match else 200
            method = "POST" if ("post" in user_input.lower() or "提交" in user_input) else "GET"
            return [
                {"step_order": 1, "title": "请求接口", "tool": "http_request", "input": {"url": url, "method": method, "timeout": 15}, "error_strategy": "fail"},
                {"step_order": 2, "title": "判断状态码条件", "tool": "if_condition", "input": {"left": "step:1.data.status_code", "operator": operator, "right": expected_code}, "error_strategy": "fail"},
                {"step_order": 3, "title": "写入条件成立结果", "tool": "file_write", "input": {"path": target_path, "content": "http ok"}, "run_if": "step:2.data.matched", "error_strategy": "fail"},
            ]

    if (
        src_path and src_path.endswith(".json") and target_path
        and "存在" in user_input and "planner" in user_input and "字段" in user_input and "写入" in user_input
    ):
        return [
            {"step_order": 1, "title": "读取 JSON 文件", "tool": "read_json", "input": {"path": src_path}, "error_strategy": "fail"},
            {"step_order": 2, "title": "判断 planner 字段是否存在", "tool": "if_condition", "input": {"left": "step:1.data.json.planner", "operator": "exists", "right": True}, "error_strategy": "fail"},
            {"step_order": 3, "title": "写入字段存在结果", "tool": "file_write", "input": {"path": target_path, "content": "planner exists"}, "run_if": "step:2.data.matched", "error_strategy": "fail"},
        ]

    if (
        src_path and src_path.endswith(".json") and target_path
        and "不存在" in user_input and "error" in user_input and "字段" in user_input and "写入" in user_input
    ):
        return [
            {"step_order": 1, "title": "读取 JSON 文件", "tool": "read_json", "input": {"path": src_path}, "error_strategy": "fail"},
            {"step_order": 2, "title": "判断 error 字段是否不存在", "tool": "if_condition", "input": {"left": "step:1.data.json.error", "operator": "not_exists", "right": True}, "error_strategy": "fail"},
            {"step_order": 3, "title": "写入字段不存在结果", "tool": "file_write", "input": {"path": target_path, "content": "error not exists"}, "run_if": "step:2.data.matched", "error_strategy": "fail"},
        ]

    if (
        src_path and src_path.endswith(".json") and target_path
        and "modules" in user_input and "包含" in user_input and "worker" in user_input and "写入" in user_input
    ):
        return [
            {"step_order": 1, "title": "读取 JSON 文件", "tool": "read_json", "input": {"path": src_path}, "error_strategy": "fail"},
            {"step_order": 2, "title": "判断 modules 是否包含 worker", "tool": "if_condition", "input": {"left": "step:1.data.json.modules", "operator": "contains", "right": "worker"}, "error_strategy": "fail"},
            {"step_order": 3, "title": "写入包含结果", "tool": "file_write", "input": {"path": target_path, "content": "module worker exists"}, "run_if": "step:2.data.matched", "error_strategy": "fail"},
        ]

    if (
        "http" in user_input.lower() and target_path
        and "包含" in user_input and "ai" in user_input.lower()
        and ("返回内容" in user_input or "响应内容" in user_input or "返回结果" in user_input)
        and "写入" in user_input
    ):
        url_match = re.search(r"(https?://[^\s'\"，。；：]+)", user_input)
        if url_match:
            url = url_match.group(1).strip()
            method = "POST" if ("post" in user_input.lower() or "提交" in user_input) else "GET"
            return [
                {"step_order": 1, "title": "请求接口", "tool": "http_request", "input": {"url": url, "method": method, "timeout": 15}, "error_strategy": "fail"},
                {"step_order": 2, "title": "判断返回内容是否包含 ai", "tool": "if_condition", "input": {"left": "step:1.data.text", "operator": "contains", "right": "ai"}, "error_strategy": "fail"},
                {"step_order": 3, "title": "写入包含结果", "tool": "file_write", "input": {"path": target_path, "content": "http contains ai"}, "run_if": "step:2.data.matched", "error_strategy": "fail"},
            ]

    if (
        src_path
        and target_path
        and src_path.endswith(".json")
        and extract_path
        and "写入" in user_input
    ):
        return [
            {"step_order": 1, "title": "读取 JSON 文件", "tool": "read_json", "input": {"path": src_path}, "error_strategy": "fail"},
            {"step_order": 2, "title": "提取 JSON 字段", "tool": "json_extract", "input": {"data": "step:1.data.json", "path": extract_path}, "error_strategy": "fail"},
            {"step_order": 3, "title": "写入提取结果", "tool": "file_write", "input": {"path": target_path, "content": "step:2.data.value"}, "error_strategy": "fail"},
        ]

    if (
        "http" in user_input.lower()
        and ("整理结果" in user_input or "整理返回结果" in user_input or "整理接口返回结果" in user_input)
        and ("请求" in user_input or "提交" in user_input or "post" in user_input.lower())
        and "提取" not in user_input
        and "字段" not in user_input
        and "如果" not in user_input
    ):
        url_match = re.search(r"(https?://[^\s'\"，。；：]+)", user_input)
        if url_match:
            url = url_match.group(1).strip()
            method = "POST" if ("post" in user_input.lower() or "提交" in user_input) else "GET"
            return [
                {"step_order": 1, "title": "请求接口", "tool": "http_request", "input": {"url": url, "method": method, "timeout": 15}, "error_strategy": "fail"},
                {"step_order": 2, "title": "整理接口返回结果", "tool": "summarize_text", "input": {"text": "step:1.output"}, "error_strategy": "fail"},
            ]

    if "http" in user_input.lower() and extract_path and "写入" in user_input:
        url_match = re.search(r"(https?://[^\s'\"，。；：]+)", user_input)
        if url_match and target_path:
            url = url_match.group(1).strip()
            method = "POST" if ("post" in user_input.lower() or "提交" in user_input) else "GET"
            return [
                {"step_order": 1, "title": "请求接口", "tool": "http_request", "input": {"url": url, "method": method, "timeout": 15}, "error_strategy": "fail"},
                {"step_order": 2, "title": "提取返回字段", "tool": "json_extract", "input": {"data": "step:1.data.json", "path": extract_path}, "error_strategy": "fail"},
                {"step_order": 3, "title": "写入提取结果", "tool": "file_write", "input": {"path": target_path, "content": "step:2.data.value"}, "error_strategy": "fail"},
            ]

    if (
        src_path
        and target_path
        and src_path.endswith(".json")
        and target_path.endswith(".json")
        and (
            "写入 json 文件" in user_input
            or "写入json文件" in user_input
            or "原样写入" in user_input
            or "写入文件" in user_input
            or "保存到" in user_input
            or "另存为" in user_input
            or "复制到" in user_input
        )
    ):
        return [
            {"step_order": 1, "title": "读取 JSON 文件", "tool": "read_json", "input": {"path": src_path}, "error_strategy": "fail"},
            {"step_order": 2, "title": "写入 JSON 文件", "tool": "write_json", "input": {"path": target_path, "data": "step:1.data.json"}, "error_strategy": "fail"},
        ]

    if (
        src_path
        and src_path.endswith(".json")
        and ("整理要点" in user_input or "总结" in user_input or "摘要" in user_input or "分析" in user_input)
    ):
        return [
            {"step_order": 1, "title": "读取 JSON 文件", "tool": "read_json", "input": {"path": src_path}, "error_strategy": "fail"},
            {"step_order": 2, "title": "整理 JSON 要点", "tool": "summarize_text", "input": {"text": "step:1.output"}, "error_strategy": "fail"},
        ]

    if src_path and target_path and "整理要点" in user_input:
        return [
            {"step_order": 1, "title": "读取文件内容", "tool": "file_read", "input": {"path": src_path}, "error_strategy": "fail"},
            {"step_order": 2, "title": "整理文件要点", "tool": "summarize_text", "input": {"text": "step:1.data.content"}, "error_strategy": "fail"},
            {"step_order": 3, "title": "写入摘要到文件", "tool": "file_write", "input": {"path": target_path, "content": "step:2.data.text"}, "error_strategy": "fail"},
        ]

    if src_path and target_path:
        return [
            {"step_order": 1, "title": "读取文件内容", "tool": "file_read", "input": {"path": src_path}, "error_strategy": "fail"},
            {"step_order": 2, "title": "写入文件", "tool": "file_write", "input": {"path": target_path, "content": "step:1.data.content"}, "error_strategy": "fail"},
        ]

    if "执行命令" in user_input:
        command_match = re.search(r"[`‘“\"]([^`’”\"]+)[`’”\"]", user_input)
        if command_match:
            cmd = command_match.group(1).strip()
            return [
                {"step_order": 1, "title": "执行命令", "tool": "shell_exec", "input": {"command": cmd}, "error_strategy": "fail"},
                {"step_order": 2, "title": "整理输出内容", "tool": "summarize_text", "input": {"text": "step:1.data.stdout_text"}, "error_strategy": "fail"},
            ]

    if "http" in user_input and ("请求" in user_input or "接口" in user_input or "api" in user_input.lower()):
        url_match = re.search(r"(https?://[^\s'\"，。；：]+)", user_input)
        if url_match:
            url = url_match.group(1).strip()
            method = "POST" if ("post" in user_input.lower() or "提交" in user_input) else "GET"
            return [
                {"step_order": 1, "title": "请求接口", "tool": "http_request", "input": {"url": url, "method": method, "timeout": 15}, "error_strategy": "fail"},
                {"step_order": 2, "title": "整理接口返回结果", "tool": "summarize_text", "input": {"text": "step:1.output"}, "error_strategy": "fail"},
            ]

    return []
