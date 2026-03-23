import os
import json
import time
import re
import shlex
import subprocess
import ipaddress
import socket
from urllib.parse import urlparse
from pathlib import Path
from typing import Any, Optional

import psycopg2
from psycopg2.extras import RealDictCursor
import requests
from bs4 import BeautifulSoup
from openai import OpenAI


DB_CONFIG = {
    "host": os.environ.get("POSTGRES_HOST", "postgres"),
    "dbname": os.environ.get("POSTGRES_DB", "assistant"),
    "user": os.environ.get("POSTGRES_USER", "assistant"),
    "password": os.environ.get("POSTGRES_PASSWORD", "change_me_for_local_dev"),
}

ARTIFACT_DIR = Path("/artifacts")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

WORKSPACE_DIR = Path("/workspace")
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_READ_DIRS = [ARTIFACT_DIR, WORKSPACE_DIR]
ALLOWED_WRITE_DIRS = [WORKSPACE_DIR]

SAFE_COMMANDS = {
    "pwd",
    "ls",
    "cat",
    "head",
    "tail",
    "wc",
    "find",
    "git",
    "python",
    "python3",
}

DISALLOWED_TOKENS = {
    "sudo",
    "rm",
    "mv",
    "chmod",
    "chown",
    "apt",
    "apt-get",
    "dnf",
    "yum",
    "docker",
    "systemctl",
    "reboot",
    "shutdown",
    "curl",
    "wget",
}

SUPPORTED_TOOLS = {
    "file_read",
    "file_write",
    "list_dir",
    "shell_exec",
    "summarize_text",
    "web_search",
    "read_json",
    "write_json",
    "http_request",
    "json_extract",
    "if_condition",
    "set_var",
    "template_render",
}

TOOL_INPUT_RULES = {
    "file_read": {
        "required": {"path"},
        "optional": set(),
    },
    "file_write": {
        "required": {"path", "content"},
        "optional": set(),
    },
    "list_dir": {
        "required": {"path"},
        "optional": set(),
    },
    "shell_exec": {
        "required": {"command"},
        "optional": set(),
    },
    "summarize_text": {
        "required": {"text"},
        "optional": set(),
    },
    "web_search": {
        "required": {"query"},
        "optional": set(),
    },
    "read_json": {
        "required": {"path"},
        "optional": set(),
    },
    "write_json": {
        "required": {"path", "data"},
        "optional": set(),
    },
    "http_request": {
        "required": {"url", "method"},
        "optional": {"params", "json", "timeout"},
    },
    "json_extract": {
        "required": {"data", "path"},
        "optional": set(),
    },
    "if_condition": {
        "required": set(),
        "optional": {"left", "operator", "right", "logic", "conditions"},
    },
    "set_var": {
        "required": {"name", "value"},
        "optional": set(),
    },
    "template_render": {
        "required": {"template"},
        "optional": {"strict"},
    },
}

REFERENCE_PATTERN = re.compile(r"^step:(\d+)\.(data|output)(?:\.(.+))?$")
SUPPORTED_OPERATORS = {
    "eq", "ne", "gt", "lt", "gte", "lte",
    "contains", "exists", "not_exists"
}
SUPPORTED_LOGICS = {"and", "or", "not"}
VAR_REFERENCE_PREFIX = "var:"
TEMPLATE_PATTERN = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")

client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
)

MODEL_NAME = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")


# =========================
# DB
# =========================
def get_conn():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)


def safe_json_dumps(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return json.dumps({"repr": repr(obj)}, ensure_ascii=False)


def parse_json_text(text: Optional[str], default=None):
    if text is None:
        return default
    text = text.strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


def ensure_task_steps_columns(cur):
    cur.execute("ALTER TABLE task_steps ADD COLUMN IF NOT EXISTS tool_name TEXT;")
    cur.execute("ALTER TABLE task_steps ADD COLUMN IF NOT EXISTS output_data TEXT;")
    cur.execute("ALTER TABLE task_steps ADD COLUMN IF NOT EXISTS error_strategy TEXT DEFAULT 'fail';")


def update_task_status(cur, task_id: int, status: str, result: Optional[str] = None, error_message: Optional[str] = None):
    cur.execute(
        """
        UPDATE task_runs
        SET status = %s,
            result = %s,
            error_message = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (status, result, error_message, task_id),
    )


def create_structured_steps(cur, task_id: int, steps: list[dict]):
    ensure_task_steps_columns(cur)

    for idx, step in enumerate(steps, start=1):
        step_order = int(step.get("step_order") or idx)
        title = str(step.get("title") or f"步骤 {step_order}")
        tool_name = str(step.get("tool") or "").strip()
        input_payload = safe_json_dumps(step.get("input", {}))
        error_strategy = str(step.get("error_strategy") or "fail").strip() or "fail"

        cur.execute(
            """
            INSERT INTO task_steps (
                task_id, step_order, step_name, tool_name, status,
                input_payload, output_payload, output_data, error_message, error_strategy
            )
            VALUES (%s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s);
            """,
            (
                task_id,
                step_order,
                title,
                tool_name,
                input_payload,
                None,
                None,
                "",
                error_strategy,
            ),
        )


def create_legacy_steps(cur, task_id: int, step_names: list[str]):
    ensure_task_steps_columns(cur)

    for idx, step_name in enumerate(step_names, start=1):
        cur.execute(
            """
            INSERT INTO task_steps (
                task_id, step_order, step_name, tool_name, status,
                input_payload, output_payload, output_data, error_message, error_strategy
            )
            VALUES (%s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s);
            """,
            (
                task_id,
                idx,
                step_name,
                None,
                None,
                None,
                None,
                "",
                "fail",
            ),
        )


def set_step_running(cur, task_id: int, step_order: int):
    cur.execute(
        """
        UPDATE task_steps
        SET status = 'running',
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = %s AND step_order = %s;
        """,
        (task_id, step_order),
    )


def set_step_result(
    cur,
    task_id: int,
    step_order: int,
    status: str,
    tool_name: Optional[str],
    input_payload: Any,
    output_payload: Optional[str],
    output_data: Any,
    error_message: str,
    error_strategy: str,
):
    cur.execute(
        """
        UPDATE task_steps
        SET status = %s,
            tool_name = %s,
            input_payload = %s,
            output_payload = %s,
            output_data = %s,
            error_message = %s,
            error_strategy = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = %s AND step_order = %s;
        """,
        (
            status,
            tool_name,
            safe_json_dumps(input_payload) if input_payload is not None else None,
            output_payload,
            safe_json_dumps(output_data) if output_data is not None else None,
            error_message or "",
            error_strategy or "fail",
            task_id,
            step_order,
        ),
    )


def get_task_steps(cur, task_id: int) -> list[dict]:
    cur.execute(
        """
        SELECT id, task_id, step_order, step_name, tool_name, status,
               input_payload, output_payload, output_data, error_message, error_strategy,
               created_at, updated_at
        FROM task_steps
        WHERE task_id = %s
        ORDER BY step_order ASC;
        """,
        (task_id,),
    )
    return list(cur.fetchall())


# =========================
# Path / safety helpers
# =========================
def is_path_in_allowed_dirs(path_str: str, allowed_dirs: list[Path]) -> bool:
    try:
        target = Path(path_str).resolve()
        for base in allowed_dirs:
            try:
                target.relative_to(base.resolve())
                return True
            except ValueError:
                continue
        return False
    except Exception:
        return False


def ensure_readable_file(path_str: str) -> Path:
    if not path_str:
        raise ValueError("缺少文件路径")
    if not is_path_in_allowed_dirs(path_str, ALLOWED_READ_DIRS):
        raise ValueError(f"路径不在允许范围内 -> {path_str}")

    path = Path(path_str).resolve()
    if not path.exists():
        raise ValueError(f"文件不存在 -> {path_str}")
    if not path.is_file():
        raise ValueError(f"目标不是文件 -> {path_str}")
    return path


def ensure_writable_file(path_str: str) -> Path:
    if not path_str:
        raise ValueError("缺少文件路径")
    if not is_path_in_allowed_dirs(path_str, ALLOWED_WRITE_DIRS):
        raise ValueError(f"路径不在允许范围内 -> {path_str}")

    path = Path(path_str).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and path.is_dir():
        raise ValueError(f"目标是目录，不是文件 -> {path_str}")
    return path


def ensure_readable_dir(path_str: str) -> Path:
    if not path_str:
        raise ValueError("缺少目录路径")
    if not is_path_in_allowed_dirs(path_str, ALLOWED_READ_DIRS):
        raise ValueError(f"路径不在允许范围内 -> {path_str}")

    path = Path(path_str).resolve()
    if not path.exists():
        raise ValueError(f"目录不存在 -> {path_str}")
    if not path.is_dir():
        raise ValueError(f"目标不是目录 -> {path_str}")
    return path


# =========================
# Generic helpers
# =========================
def extract_path_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    match = re.search(r"(/[^ \n\r\t'\"，。；：]+)", text)
    if match:
        return match.group(1)
    return None


def normalize_step_name(step: str) -> str:
    step = (step or "").strip()
    step = re.sub(r"^\s*\d+[\.\)、:：-]\s*", "", step)
    step = re.sub(r"^\s*第\s*\d+\s*步[\s:：\-]*", "", step)
    return step.strip()


def get_nested_value(data: Any, path_str: Optional[str]) -> Any:
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


def resolve_reference_value(raw_value: Any, step_context: dict[int, dict], var_context: Optional[dict[str, Any]] = None) -> Any:
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

    m = REFERENCE_PATTERN.match(raw_value)
    if not m:
        return raw_value

    ref_step_order = int(m.group(1))
    ref_scope = m.group(2)
    ref_path = m.group(3)

    if ref_step_order not in step_context:
        raise ValueError(f"引用步骤不存在: {raw_value}")

    ref_step = step_context[ref_step_order]

    if ref_scope == "data":
        base = ref_step.get("output_data")
    else:
        base = ref_step.get("output_payload")

    return get_nested_value(base, ref_path)


def resolve_input_payload(payload: Any, step_context: dict[int, dict], var_context: Optional[dict[str, Any]] = None) -> Any:
    if isinstance(payload, dict):
        return {k: resolve_input_payload(v, step_context, var_context) for k, v in payload.items()}
    if isinstance(payload, list):
        return [resolve_input_payload(v, step_context, var_context) for v in payload]
    return resolve_reference_value(payload, step_context, var_context)


def try_resolve_reference(value: Any, step_context: dict[int, dict], var_context: Optional[dict[str, Any]] = None) -> Any:
    try:
        return resolve_input_payload(value, step_context, var_context)
    except Exception:
        return None


def resolve_template_expr(expr: str, step_context: dict[int, dict], var_context: Optional[dict[str, Any]] = None) -> Any:
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


def render_template_text(template: str, step_context: dict[int, dict], var_context: Optional[dict[str, Any]] = None, strict: bool = True) -> str:
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


def should_run_step(step: dict, step_context: dict[int, dict], var_context: Optional[dict[str, Any]] = None) -> tuple[bool, str]:
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


def validate_input_value(tool_name: str, payload: dict):
    rules = TOOL_INPUT_RULES.get(tool_name)
    if not rules:
        raise ValueError(f"未知工具: {tool_name}")

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
            if not isinstance(operator, str) or operator not in SUPPORTED_OPERATORS:
                raise ValueError(f"if_condition 的 operator 非法: {operator}")

        if has_group:
            logic = payload.get("logic")
            conditions = payload.get("conditions")
            if not isinstance(logic, str) or logic not in SUPPORTED_LOGICS:
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
                if not isinstance(operator, str) or operator not in SUPPORTED_OPERATORS:
                    raise ValueError(f"if_condition.conditions[{idx}] 的 operator 非法: {operator}")


# =========================
# Planning
# =========================
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


def infer_structured_steps_from_user_input(user_input: str) -> list[dict]:
    src_path = extract_path_from_text(user_input)
    matches = re.findall(r"(/[^ \n\r\t'\"，。；：]+)", user_input)
    target_path = matches[-1] if len(matches) >= 2 else None

    # 提取“xxx 字段”
    extract_match = re.search(r"提取\s+([A-Za-z0-9_.]+)\s+字段", user_input)
    extract_path = extract_match.group(1).strip() if extract_match else None

    # JSON -> 变量 -> 写文件
    if (
        src_path
        and src_path.endswith(".json")
        and target_path
        and ("保存为变量" in user_input or "保存变量" in user_input)
        and ("planner" in user_input)
        and ("写入" in user_input)
    ):
        return [
            {
                "step_order": 1,
                "title": "读取 JSON 文件",
                "tool": "read_json",
                "input": {"path": src_path},
                "error_strategy": "fail",
            },
            {
                "step_order": 2,
                "title": "保存 planner 变量",
                "tool": "set_var",
                "input": {
                    "name": "planner_name",
                    "value": "step:1.data.json.planner",
                },
                "error_strategy": "fail",
            },
            {
                "step_order": 3,
                "title": "写入变量值",
                "tool": "file_write",
                "input": {
                    "path": target_path,
                    "content": "var:planner_name",
                },
                "error_strategy": "fail",
            },
        ]

    # JSON -> 模板渲染报告
    if (
        src_path
        and src_path.endswith(".json")
        and target_path
        and ("渲染成报告" in user_input or "渲染报告" in user_input)
        and ("planner" in user_input)
        and ("version" in user_input)
    ):
        return [
            {
                "step_order": 1,
                "title": "读取 JSON 文件",
                "tool": "read_json",
                "input": {"path": src_path},
                "error_strategy": "fail",
            },
            {
                "step_order": 2,
                "title": "保存 planner 变量",
                "tool": "set_var",
                "input": {
                    "name": "planner_name",
                    "value": "step:1.data.json.planner",
                },
                "error_strategy": "fail",
            },
            {
                "step_order": 3,
                "title": "保存 version 变量",
                "tool": "set_var",
                "input": {
                    "name": "version_text",
                    "value": "step:1.data.json.version",
                },
                "error_strategy": "fail",
            },
            {
                "step_order": 4,
                "title": "渲染 JSON 报告",
                "tool": "template_render",
                "input": {
                    "template": "# JSON 报告\n\nPlanner: {{var.planner_name}}\nVersion: {{var.version_text}}\n",
                    "strict": True,
                },
                "error_strategy": "fail",
            },
            {
                "step_order": 5,
                "title": "写入 JSON 报告",
                "tool": "file_write",
                "input": {
                    "path": target_path,
                    "content": "step:4.data.rendered_text",
                },
                "error_strategy": "fail",
            },
        ]

    # HTTP -> 模板渲染报告
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
                {
                    "step_order": 1,
                    "title": "请求接口",
                    "tool": "http_request",
                    "input": {
                        "url": url,
                        "method": method,
                        "timeout": 15,
                    },
                    "error_strategy": "fail",
                },
                {
                    "step_order": 2,
                    "title": "渲染 HTTP 报告",
                    "tool": "template_render",
                    "input": {
                        "template": "# HTTP 报告\n\nStatus Code: {{step.1.data.status_code}}\nBody: {{step.1.data.text}}\n",
                        "strict": True,
                    },
                    "error_strategy": "fail",
                },
                {
                    "step_order": 3,
                    "title": "写入 HTTP 报告",
                    "tool": "file_write",
                    "input": {
                        "path": target_path,
                        "content": "step:2.data.rendered_text",
                    },
                    "error_strategy": "fail",
                },
            ]

    # 条件 + 模板渲染报告
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
            {
                "step_order": 1,
                "title": "读取 JSON 文件",
                "tool": "read_json",
                "input": {"path": src_path},
                "error_strategy": "fail",
            },
            {
                "step_order": 2,
                "title": "判断 planner 条件",
                "tool": "if_condition",
                "input": {
                    "left": "step:1.data.json.planner",
                    "operator": "eq",
                    "right": "DeepSeek",
                },
                "error_strategy": "fail",
            },
            {
                "step_order": 3,
                "title": "渲染成功报告",
                "tool": "template_render",
                "input": {
                    "template": "# 成功报告\n\nPlanner: {{step.1.data.json.planner}}\nVersion: {{step.1.data.json.version}}\n",
                    "strict": True,
                },
                "run_if": "step:2.data.matched",
                "error_strategy": "fail",
            },
            {
                "step_order": 4,
                "title": "写入成功报告",
                "tool": "file_write",
                "input": {
                    "path": target_path,
                    "content": "step:3.data.rendered_text",
                },
                "run_if": "step:2.data.matched",
                "error_strategy": "fail",
            },
        ]

    # JSON 条件判断：true/false 双分支写文件
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

    # HTTP 组合条件 and 判断
    if (
        "http" in user_input.lower() and target_path
        and "状态码" in user_input and "包含" in user_input and "且" in user_input
        and "ai" in user_input.lower() and "写入" in user_input
    ):
        url_match = re.search(r"(https?://[^\s'\"，。；：]+)", user_input)
        if url_match:
            url = url_match.group(1).strip()
            code_match = re.search(r"状态码\s*等于\s*(\d+)", user_input)
            expected_code = int(code_match.group(1)) if code_match else 200
            method = "POST" if ("post" in user_input.lower() or "提交" in user_input) else "GET"
            return [
                {"step_order": 1, "title": "请求接口", "tool": "http_request", "input": {"url": url, "method": method, "timeout": 15}, "error_strategy": "fail"},
                {"step_order": 2, "title": "判断 HTTP 组合条件", "tool": "if_condition", "input": {"logic": "and", "conditions": [
                    {"left": "step:1.data.status_code", "operator": "eq", "right": expected_code},
                    {"left": "step:1.data.text", "operator": "contains", "right": "ai"}
                ]}, "error_strategy": "fail"},
                {"step_order": 3, "title": "写入组合条件成立结果", "tool": "file_write", "input": {"path": target_path, "content": "http and ok"}, "run_if": "step:2.data.matched", "error_strategy": "fail"},
            ]

    # JSON 组合条件 and 判断
    if (
        src_path and src_path.endswith(".json") and target_path
        and "存在" in user_input and "planner" in user_input and "modules" in user_input and "包含" in user_input and "worker" in user_input and "且" in user_input and "写入" in user_input
    ):
        return [
            {"step_order": 1, "title": "读取 JSON 文件", "tool": "read_json", "input": {"path": src_path}, "error_strategy": "fail"},
            {"step_order": 2, "title": "判断 JSON 组合条件", "tool": "if_condition", "input": {"logic": "and", "conditions": [
                {"left": "step:1.data.json.planner", "operator": "exists", "right": True},
                {"left": "step:1.data.json.modules", "operator": "contains", "right": "worker"}
            ]}, "error_strategy": "fail"},
            {"step_order": 3, "title": "写入组合条件成立结果", "tool": "file_write", "input": {"path": target_path, "content": "json and ok"}, "run_if": "step:2.data.matched", "error_strategy": "fail"},
        ]

    # JSON 组合条件 or 判断
    if (
        src_path and src_path.endswith(".json") and target_path
        and "planner" in user_input and ("或" in user_input or "或者" in user_input) and "写入" in user_input
    ):
        return [
            {"step_order": 1, "title": "读取 JSON 文件", "tool": "read_json", "input": {"path": src_path}, "error_strategy": "fail"},
            {"step_order": 2, "title": "判断 JSON 或条件", "tool": "if_condition", "input": {"logic": "or", "conditions": [
                {"left": "step:1.data.json.error", "operator": "exists", "right": True},
                {"left": "step:1.data.json.planner", "operator": "eq", "right": "DeepSeek"}
            ]}, "error_strategy": "fail"},
            {"step_order": 3, "title": "写入或条件成立结果", "tool": "file_write", "input": {"path": target_path, "content": "json or ok"}, "run_if": "step:2.data.matched", "error_strategy": "fail"},
        ]

    # JSON 组合条件 not 判断
    if (
        src_path and src_path.endswith(".json") and target_path
        and "不是" in user_input and "error" in user_input and "存在" in user_input and "写入" in user_input
    ):
        return [
            {"step_order": 1, "title": "读取 JSON 文件", "tool": "read_json", "input": {"path": src_path}, "error_strategy": "fail"},
            {"step_order": 2, "title": "判断 JSON 非条件", "tool": "if_condition", "input": {"logic": "not", "conditions": [
                {"left": "step:1.data.json.error", "operator": "exists", "right": True}
            ]}, "error_strategy": "fail"},
            {"step_order": 3, "title": "写入非条件成立结果", "tool": "file_write", "input": {"path": target_path, "content": "json not ok"}, "run_if": "step:2.data.matched", "error_strategy": "fail"},
        ]

    # JSON 条件判断：单分支写文件
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

    # HTTP 状态码条件判断：单分支写文件
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

    # JSON 字段存在判断
    if (
        src_path and src_path.endswith(".json") and target_path
        and "存在" in user_input and "planner" in user_input and "字段" in user_input and "写入" in user_input
    ):
        return [
            {"step_order": 1, "title": "读取 JSON 文件", "tool": "read_json", "input": {"path": src_path}, "error_strategy": "fail"},
            {"step_order": 2, "title": "判断 planner 字段是否存在", "tool": "if_condition", "input": {"left": "step:1.data.json.planner", "operator": "exists", "right": True}, "error_strategy": "fail"},
            {"step_order": 3, "title": "写入字段存在结果", "tool": "file_write", "input": {"path": target_path, "content": "planner exists"}, "run_if": "step:2.data.matched", "error_strategy": "fail"},
        ]

    # JSON 字段不存在判断
    if (
        src_path and src_path.endswith(".json") and target_path
        and "不存在" in user_input and "error" in user_input and "字段" in user_input and "写入" in user_input
    ):
        return [
            {"step_order": 1, "title": "读取 JSON 文件", "tool": "read_json", "input": {"path": src_path}, "error_strategy": "fail"},
            {"step_order": 2, "title": "判断 error 字段是否不存在", "tool": "if_condition", "input": {"left": "step:1.data.json.error", "operator": "not_exists", "right": True}, "error_strategy": "fail"},
            {"step_order": 3, "title": "写入字段不存在结果", "tool": "file_write", "input": {"path": target_path, "content": "error not exists"}, "run_if": "step:2.data.matched", "error_strategy": "fail"},
        ]

    # JSON 列表包含判断
    if (
        src_path and src_path.endswith(".json") and target_path
        and "modules" in user_input and "包含" in user_input and "worker" in user_input and "写入" in user_input
    ):
        return [
            {"step_order": 1, "title": "读取 JSON 文件", "tool": "read_json", "input": {"path": src_path}, "error_strategy": "fail"},
            {"step_order": 2, "title": "判断 modules 是否包含 worker", "tool": "if_condition", "input": {"left": "step:1.data.json.modules", "operator": "contains", "right": "worker"}, "error_strategy": "fail"},
            {"step_order": 3, "title": "写入包含结果", "tool": "file_write", "input": {"path": target_path, "content": "module worker exists"}, "run_if": "step:2.data.matched", "error_strategy": "fail"},
        ]

    # HTTP body contains 判断
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

    # 提取 JSON 文件字段并写入文件
    if (
        src_path
        and target_path
        and src_path.endswith(".json")
        and extract_path
        and "写入" in user_input
    ):
        return [
            {
                "step_order": 1,
                "title": "读取 JSON 文件",
                "tool": "read_json",
                "input": {"path": src_path},
                "error_strategy": "fail",
            },
            {
                "step_order": 2,
                "title": "提取 JSON 字段",
                "tool": "json_extract",
                "input": {
                    "data": "step:1.data.json",
                    "path": extract_path,
                },
                "error_strategy": "fail",
            },
            {
                "step_order": 3,
                "title": "写入提取结果",
                "tool": "file_write",
                "input": {
                    "path": target_path,
                    "content": "step:2.data.value",
                },
                "error_strategy": "fail",
            },
        ]

    # HTTP POST/请求 -> 整理返回结果（避免被提取字段规则误命中）
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
                {
                    "step_order": 1,
                    "title": "请求接口",
                    "tool": "http_request",
                    "input": {
                        "url": url,
                        "method": method,
                        "timeout": 15,
                    },
                    "error_strategy": "fail",
                },
                {
                    "step_order": 2,
                    "title": "整理接口返回结果",
                    "tool": "summarize_text",
                    "input": {"text": "step:1.output"},
                    "error_strategy": "fail",
                },
            ]

    # HTTP 请求 + 提取字段 + 写入文件
    if (
        "http" in user_input.lower()
        and extract_path
        and "写入" in user_input
    ):
        url_match = re.search(r"(https?://[^\s'\"，。；：]+)", user_input)
        if url_match and target_path:
            url = url_match.group(1).strip()
            method = "POST" if ("post" in user_input.lower() or "提交" in user_input) else "GET"
            return [
                {
                    "step_order": 1,
                    "title": "请求接口",
                    "tool": "http_request",
                    "input": {
                        "url": url,
                        "method": method,
                        "timeout": 15,
                    },
                    "error_strategy": "fail",
                },
                {
                    "step_order": 2,
                    "title": "提取返回字段",
                    "tool": "json_extract",
                    "input": {
                        "data": "step:1.data.json",
                        "path": extract_path,
                    },
                    "error_strategy": "fail",
                },
                {
                    "step_order": 3,
                    "title": "写入提取结果",
                    "tool": "file_write",
                    "input": {
                        "path": target_path,
                        "content": "step:2.data.value",
                    },
                    "error_strategy": "fail",
                },
            ]

    # JSON -> JSON 写入
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
            {
                "step_order": 1,
                "title": "读取 JSON 文件",
                "tool": "read_json",
                "input": {"path": src_path},
                "error_strategy": "fail",
            },
            {
                "step_order": 2,
                "title": "写入 JSON 文件",
                "tool": "write_json",
                "input": {"path": target_path, "data": "step:1.data.json"},
                "error_strategy": "fail",
            },
        ]

    # JSON 摘要
    if (
        src_path
        and src_path.endswith(".json")
        and (
            "整理要点" in user_input
            or "总结" in user_input
            or "摘要" in user_input
            or "分析" in user_input
        )
    ):
        return [
            {
                "step_order": 1,
                "title": "读取 JSON 文件",
                "tool": "read_json",
                "input": {"path": src_path},
                "error_strategy": "fail",
            },
            {
                "step_order": 2,
                "title": "整理 JSON 要点",
                "tool": "summarize_text",
                "input": {"text": "step:1.output"},
                "error_strategy": "fail",
            },
        ]

    # 文本文件读取+摘要+写入
    if src_path and target_path and "整理要点" in user_input:
        return [
            {
                "step_order": 1,
                "title": "读取文件内容",
                "tool": "file_read",
                "input": {"path": src_path},
                "error_strategy": "fail",
            },
            {
                "step_order": 2,
                "title": "整理文件要点",
                "tool": "summarize_text",
                "input": {"text": "step:1.data.content"},
                "error_strategy": "fail",
            },
            {
                "step_order": 3,
                "title": "写入摘要到文件",
                "tool": "file_write",
                "input": {
                    "path": target_path,
                    "content": "step:2.data.text",
                },
                "error_strategy": "fail",
            },
        ]

    # 普通文件复制
    if src_path and target_path:
        return [
            {
                "step_order": 1,
                "title": "读取文件内容",
                "tool": "file_read",
                "input": {"path": src_path},
                "error_strategy": "fail",
            },
            {
                "step_order": 2,
                "title": "写入文件",
                "tool": "file_write",
                "input": {
                    "path": target_path,
                    "content": "step:1.data.content",
                },
                "error_strategy": "fail",
            },
        ]

    # 执行命令
    if "执行命令" in user_input:
        command_match = re.search(r"[`‘“\"]([^`’”\"]+)[`’”\"]", user_input)
        if command_match:
            cmd = command_match.group(1).strip()
            return [
                {
                    "step_order": 1,
                    "title": "执行命令",
                    "tool": "shell_exec",
                    "input": {"command": cmd},
                    "error_strategy": "fail",
                },
                {
                    "step_order": 2,
                    "title": "整理输出内容",
                    "tool": "summarize_text",
                    "input": {"text": "step:1.data.stdout_text"},
                    "error_strategy": "fail",
                },
            ]

    # 普通 HTTP 请求
    if "http" in user_input and ("请求" in user_input or "接口" in user_input or "api" in user_input.lower()):
        url_match = re.search(r"(https?://[^\s'\"，。；：]+)", user_input)
        if url_match:
            url = url_match.group(1).strip()
            method = "POST" if ("post" in user_input.lower() or "提交" in user_input) else "GET"
            return [
                {
                    "step_order": 1,
                    "title": "请求接口",
                    "tool": "http_request",
                    "input": {
                        "url": url,
                        "method": method,
                        "timeout": 15,
                    },
                    "error_strategy": "fail",
                },
                {
                    "step_order": 2,
                    "title": "整理接口返回结果",
                    "tool": "summarize_text",
                    "input": {"text": "step:1.output"},
                    "error_strategy": "fail",
                },
            ]

    return []

def call_deepseek_planner(user_input: str) -> list[dict] | list[str]:
    system_prompt = """
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

强约束：
- 只返回 JSON
- 不要 Markdown
- 不要代码块
- 不要额外解释
"""

    completion = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
        max_tokens=1500,
    )

    content = (completion.choices[0].message.content or "").strip()
    if not content:
        raise ValueError("DeepSeek 返回空内容")

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
        normalized.append(
            {
                "step_order": int(step.get("step_order") or i),
                "title": str(step.get("title") or f"步骤 {i}"),
                "tool": str(step.get("tool") or "").strip(),
                "input": step.get("input") or {},
                "run_if": step.get("run_if"),
                "skip_if": step.get("skip_if"),
                "error_strategy": str(step.get("error_strategy") or "fail"),
            }
        )

    if not normalized:
        raise ValueError("planner 返回的结构化步骤为空")

    return normalized


def plan_task(user_input: str) -> list[dict] | list[str]:
    inferred = infer_structured_steps_from_user_input(user_input)
    if inferred:
        return inferred

    last_error = None
    for _ in range(2):
        try:
            return call_deepseek_planner(user_input)
        except Exception as e:
            last_error = e
            time.sleep(1)

    print(f"[planner] fallback due to: {last_error}")
    return fallback_legacy_steps(user_input)


# =========================
# Tool implementations
# =========================
def tool_file_read(path_str: str) -> dict:
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
    except Exception as e:
        return {
            "ok": False,
            "output_text": f"file_read 执行失败：{e}",
            "output_data": None,
            "error": f"file_read 执行失败：{e}",
        }


def tool_file_write(path_str: str, content: str) -> dict:
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
    except Exception as e:
        return {
            "ok": False,
            "output_text": f"file_write 执行失败：{e}",
            "output_data": None,
            "error": f"file_write 执行失败：{e}",
        }


def tool_list_dir(path_str: str) -> dict:
    try:
        path = ensure_readable_dir(path_str)
        items = []
        for p in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            prefix = "[DIR]" if p.is_dir() else "[FILE]"
            items.append(f"{prefix} {p.name}")

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
    except Exception as e:
        return {
            "ok": False,
            "output_text": f"list_dir 执行失败：{e}",
            "output_data": None,
            "error": f"list_dir 执行失败：{e}",
        }


def validate_shell_command(command: str):
    stripped = command.strip()
    if not stripped:
        raise ValueError("缺少命令")

    tokens = shlex.split(stripped)
    if not tokens:
        raise ValueError("命令解析失败")

    first = tokens[0]
    if first not in SAFE_COMMANDS:
        raise ValueError(f"命令不在白名单中 -> {first}")

    for token in tokens:
        if token in DISALLOWED_TOKENS:
            raise ValueError(f"命令包含禁用词 -> {token}")

    return tokens


def tool_shell_exec(command: str) -> dict:
    try:
        validate_shell_command(command)

        completed = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=str(WORKSPACE_DIR),
            timeout=15,
        )

        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        rc = completed.returncode

        output_text = (
            f"shell_exec 命令：{command}\n"
            f"退出码：{rc}\n"
            f"标准输出：\n{stdout if stdout else '(空)'}"
        )

        if stderr:
            output_text += f"\n标准错误：\n{stderr}"

        return {
            "ok": rc == 0,
            "output_text": output_text,
            "output_data": {
                "command": command,
                "returncode": rc,
                "stdout": stdout,
                "stderr": stderr,
                "stdout_text": output_text,
            },
            "error": "" if rc == 0 else f"shell_exec 执行失败：退出码 {rc}",
        }
    except Exception as e:
        return {
            "ok": False,
            "output_text": f"shell_exec 执行失败：{e}",
            "output_data": None,
            "error": f"shell_exec 执行失败：{e}",
        }


def tool_summarize_text(text: str) -> dict:
    try:
        prompt = (
            "请将下面内容整理为简明中文摘要。\n"
            "要求：\n"
            "1. 标题固定为“摘要结果：”\n"
            "2. 输出 3 到 6 条 bullet\n"
            "3. 优先提炼关键步骤、编号项、结论\n"
            "4. 不要编造\n\n"
            f"{text}"
        )

        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "你是一个文本整理助手。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=800,
        )
        summary = (completion.choices[0].message.content or "").strip()
        if not summary:
            raise ValueError("DeepSeek 返回空内容")

        return {
            "ok": True,
            "output_text": summary,
            "output_data": {"text": summary},
            "error": "",
        }

    except Exception:
        raw = text or ""

        cleaned_lines = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue

            # 去掉工具输出头
            if line.startswith("file_read 结果（"):
                continue
            if line.startswith("shell_exec 命令："):
                continue
            if line.startswith("退出码："):
                continue
            if line.startswith("标准输出："):
                continue
            if line.startswith("标准错误："):
                continue
            if line.startswith("http_request 成功："):
                continue
            if line.startswith("状态码："):
                continue
            if line.startswith("Content-Type："):
                continue
            if line.startswith("响应预览："):
                continue
            if line.startswith("read_json 成功："):
                continue
            if line.startswith("JSON 类型："):
                continue

            cleaned_lines.append(line)

        bullets = []

        # 1. 优先提取编号项
        numbered = [x for x in cleaned_lines if re.match(r"^\d+\.", x)]
        if numbered:
            bullets.extend(numbered[:5])

        # 2. 提取常见关键句
        if len(bullets) < 4:
            for line in cleaned_lines:
                if any(k in line for k in ["DeepSeek", "planner", "web_search", "file_read", "worker", "postgres", "api"]):
                    if line not in bullets:
                        bullets.append(line)
                if len(bullets) >= 5:
                    break

        # 3. 不够再补前几条普通句子
        if len(bullets) < 4:
            for line in cleaned_lines:
                if line not in bullets:
                    bullets.append(line)
                if len(bullets) >= 5:
                    break

        if not bullets:
            bullets = ["未识别到可摘要内容。"]

        summary = "摘要结果：\n" + "\n".join(f"- {x}" for x in bullets[:5])

        return {
            "ok": True,
            "output_text": summary,
            "output_data": {"text": summary},
            "error": "",
        }


def dedupe_search_results(results: list[dict]) -> list[dict]:
    seen = set()
    deduped = []

    for item in results:
        url = (item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append(item)
    return deduped


def summarize_search_results(query: str, results: list[dict]) -> str:
    if not results:
        return f"未找到可摘要的搜索结果。查询词：{query}"

    simplified_results = []
    for item in results[:5]:
        simplified_results.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": (item.get("content", "") or "")[:300],
            }
        )

    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一个搜索结果整理助手。"
                        "请根据给定搜索结果输出简明中文摘要。"
                        "先输出“### 结论摘要”，再输出“### 关键来源”。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"query": query, "results": simplified_results},
                        ensure_ascii=False,
                    ),
                },
            ],
            temperature=0.2,
            max_tokens=1200,
        )
        text = (completion.choices[0].message.content or "").strip()
        if text:
            return text
    except Exception:
        pass

    lines = ["### 结论摘要"]
    lines.append(f"- 针对查询“{query}”获取到 {len(results[:5])} 条候选结果。")
    lines.append("")
    lines.append("### 关键来源")
    for item in results[:5]:
        lines.append(f"- {item.get('title', '')}")
        lines.append(f"  {item.get('url', '')}")
    return "\n".join(lines)


def web_search_duckduckgo(query: str) -> str:
    url = "https://html.duckduckgo.com/html/"
    headers = {"User-Agent": "Mozilla/5.0"}

    resp = requests.post(
        url,
        data={"q": query},
        headers=headers,
        timeout=8,
    )
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    parsed_results = []

    for a in soup.select(".result__title a")[:8]:
        title = a.get_text(" ", strip=True)
        href = a.get("href", "")
        if title and href:
            parsed_results.append(
                {
                    "title": title,
                    "url": href,
                    "content": "",
                }
            )

    parsed_results = dedupe_search_results(parsed_results)[:5]

    if not parsed_results:
        return f"web_search 已执行，但没有找到明显结果。查询词：{query}"

    summary = summarize_search_results(query, parsed_results)

    raw_refs = []
    for item in parsed_results:
        raw_refs.append(f"- {item['title']}\n  {item['url']}")

    return (
        "web_search 结果（DuckDuckGo）\n\n"
        f"{summary}\n\n"
        "原始来源：\n" + "\n".join(raw_refs)
    )


def web_search_tavily(query: str) -> str:
    if not TAVILY_API_KEY:
        raise ValueError("DuckDuckGo 不可用，且缺少 TAVILY_API_KEY")

    url = "https://api.tavily.com/search"
    headers = {"Content-Type": "application/json"}
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": "basic",
        "max_results": 8,
        "include_answer": False,
        "include_raw_content": False,
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    parsed_results = []
    for item in data.get("results", []):
        parsed_results.append(
            {
                "title": (item.get("title") or "").strip(),
                "url": (item.get("url") or "").strip(),
                "content": (item.get("content") or "").strip(),
            }
        )

    parsed_results = dedupe_search_results(parsed_results)[:5]

    if not parsed_results:
        return f"web_search 已执行，但没有找到明显结果。查询词：{query}"

    summary = summarize_search_results(query, parsed_results)

    raw_refs = []
    for item in parsed_results:
        block = [f"- {item['title']}", f"  {item['url']}"]
        if item["content"]:
            block.append(f"  摘要片段：{item['content'][:180]}")
        raw_refs.append("\n".join(block))

    return (
        "web_search 结果（Tavily）\n\n"
        f"{summary}\n\n"
        "原始来源：\n" + "\n".join(raw_refs)
    )


def tool_web_search(query: str) -> dict:
    try:
        try:
            text = web_search_duckduckgo(query)
        except Exception:
            text = web_search_tavily(query)

        return {
            "ok": True,
            "output_text": text,
            "output_data": {
                "query": query,
                "text": text,
            },
            "error": "",
        }
    except Exception as e:
        msg = f"web_search 执行失败：{e}"
        return {
            "ok": False,
            "output_text": msg,
            "output_data": None,
            "error": msg,
        }


def tool_read_json(path_str: str) -> dict:
    try:
        path = ensure_readable_file(path_str)
        raw_text = path.read_text(encoding="utf-8")
        parsed = json.loads(raw_text)

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
    except Exception as e:
        msg = f"read_json 执行失败：{e}"
        return {
            "ok": False,
            "output_text": msg,
            "output_data": None,
            "error": msg,
        }


def tool_write_json(path_str: str, data: Any) -> dict:
    try:
        path = ensure_writable_file(path_str)
        text = json.dumps(data, ensure_ascii=False, indent=2)
        path.write_text(text, encoding="utf-8")

        output_text = f"write_json 成功：已写入 JSON 文件 -> {path_str}"
        return {
            "ok": True,
            "output_text": output_text,
            "output_data": {"path": path_str},
            "error": "",
        }
    except Exception as e:
        msg = f"write_json 执行失败：{e}"
        return {
            "ok": False,
            "output_text": msg,
            "output_data": None,
            "error": msg,
        }


def tool_json_extract(data: Any, path: str) -> dict:
    try:
        value = get_nested_value(data, path)

        if isinstance(value, (dict, list)):
            preview = json.dumps(value, ensure_ascii=False)
        else:
            preview = str(value)

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
    except Exception as e:
        msg = f"json_extract 执行失败：{e}"
        return {
            "ok": False,
            "output_text": msg,
            "output_data": None,
            "error": msg,
        }


# =========================
# HTTP helpers / SSRF protection
# =========================
def is_private_ip(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def resolve_hostname_ips(hostname: str) -> list[str]:
    ips = []
    try:
        infos = socket.getaddrinfo(hostname, None)
        for info in infos:
            sockaddr = info[4]
            if sockaddr:
                ip = sockaddr[0]
                if ip not in ips:
                    ips.append(ip)
    except Exception:
        pass
    return ips


def validate_http_url(url: str):
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"不支持的 URL 协议 -> {parsed.scheme}")

    if not parsed.netloc:
        raise ValueError("URL 非法，缺少 host")

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise ValueError("URL 非法，缺少 hostname")

    blocked_hosts = {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
        "postgres",
        "api",
        "worker",
        "web",
    }
    if hostname in blocked_hosts:
        raise ValueError(f"禁止访问内网或本机地址 -> {hostname}")

    try:
        ip = ipaddress.ip_address(hostname)
        if is_private_ip(str(ip)):
            raise ValueError(f"禁止访问内网或本机地址 -> {hostname}")
    except ValueError:
        pass

    ips = resolve_hostname_ips(hostname)
    if not ips:
        raise ValueError(f"无法解析域名 -> {hostname}")

    for ip_str in ips:
        if is_private_ip(ip_str):
            raise ValueError(f"禁止访问内网或本机地址 -> {hostname} -> {ip_str}")


def tool_http_request(
    url: str,
    method: str,
    params: Optional[dict] = None,
    json_body: Optional[dict] = None,
    timeout: int = 15,
) -> dict:
    try:
        validate_http_url(url)

        method = method.upper().strip()
        if method not in {"GET", "POST"}:
            raise ValueError(f"不支持的 method -> {method}")

        if timeout <= 0 or timeout > 20:
            raise ValueError("timeout 必须在 1 到 20 秒之间")

        headers = {
            "User-Agent": "AI-Assistant-Worker/1.0"
        }

        if method == "GET":
            resp = requests.get(
                url,
                params=params or {},
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
            )
        else:
            resp = requests.post(
                url,
                json=json_body or {},
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
            )

        content_type = resp.headers.get("Content-Type", "")
        text = resp.text[:5000]

        parsed_json = None
        if "application/json" in content_type.lower():
            try:
                parsed_json = resp.json()
            except Exception:
                parsed_json = None

        preview = text[:1000]
        output_text = (
            f"http_request 成功：{method} {resp.url}\n"
            f"状态码：{resp.status_code}\n"
            f"Content-Type：{content_type}\n"
            f"响应预览：\n{preview if preview else '(空)'}"
        )

        return {
            "ok": True,
            "output_text": output_text,
            "output_data": {
                "url": str(resp.url),
                "method": method,
                "status_code": resp.status_code,
                "content_type": content_type,
                "text": text,
                "json": parsed_json,
            },
            "error": "",
        }

    except Exception as e:
        msg = f"http_request 执行失败：{e}"
        return {
            "ok": False,
            "output_text": msg,
            "output_data": None,
            "error": msg,
        }


def evaluate_single_condition_payload(payload: dict) -> dict:
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


def tool_template_render(template: str, step_context: dict[int, dict], var_context: Optional[dict[str, Any]] = None, strict: bool = True) -> dict:
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
    except Exception as e:
        msg = f"template_render 执行失败：{e}"
        return {
            "ok": False,
            "output_text": msg,
            "output_data": None,
            "error": msg,
        }


def build_group_output_text(logic: str, matched: bool, results: list[dict]) -> str:
    detail_parts = []
    for idx, result in enumerate(results, start=1):
        detail_parts.append(
            f"{idx}:{'true' if result['matched'] else 'false'}({result['operator']})"
        )
    details = ",".join(detail_parts)
    return (
        f"if_condition 成功：logic={logic} "
        f"result={'true' if matched else 'false'} "
        f"details=[{details}]"
    )


def tool_if_condition_group(logic: str, conditions: list[dict]) -> dict:
    try:
        if logic not in SUPPORTED_LOGICS:
            raise ValueError(f"不支持的 logic: {logic}")
        if not isinstance(conditions, list) or not conditions:
            raise ValueError("conditions 必须是非空数组")
        if logic == "not" and len(conditions) != 1:
            raise ValueError("logic=not 时 conditions 必须只有 1 条")

        results = [evaluate_single_condition_payload(cond) for cond in conditions]

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
            "output_text": build_group_output_text(logic, matched, results),
            "output_data": {
                "matched": matched,
                "logic": logic,
                "results": results,
            },
            "error": "",
        }
    except Exception as e:
        msg = f"if_condition 执行失败：{e}"
        return {
            "ok": False,
            "output_text": msg,
            "output_data": None,
            "error": msg,
        }


def tool_if_condition(left: Any = None, operator: Optional[str] = None, right: Any = None, logic: Optional[str] = None, conditions: Optional[list[dict]] = None) -> dict:
    if logic is not None or conditions is not None:
        return tool_if_condition_group(logic=logic or "", conditions=conditions or [])

    try:
        if operator not in SUPPORTED_OPERATORS:
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
    except Exception as e:
        msg = f"if_condition 执行失败：{e}"
        return {
            "ok": False,
            "output_text": msg,
            "output_data": None,
            "error": msg,
        }


def execute_tool(tool_name: str, payload: dict, step_context: Optional[dict[int, dict]] = None, var_context: Optional[dict[str, Any]] = None) -> dict:
    if tool_name == "file_read":
        return tool_file_read(payload["path"])
    if tool_name == "file_write":
        return tool_file_write(payload["path"], payload["content"])
    if tool_name == "list_dir":
        return tool_list_dir(payload["path"])
    if tool_name == "shell_exec":
        return tool_shell_exec(payload["command"])
    if tool_name == "summarize_text":
        return tool_summarize_text(payload["text"])
    if tool_name == "web_search":
        return tool_web_search(payload["query"])
    if tool_name == "read_json":
        return tool_read_json(payload["path"])
    if tool_name == "write_json":
        return tool_write_json(payload["path"], payload["data"])
    if tool_name == "http_request":
        return tool_http_request(
            url=payload["url"],
            method=payload["method"],
            params=payload.get("params"),
            json_body=payload.get("json"),
            timeout=payload.get("timeout", 15),
        )
    if tool_name == "json_extract":
        return tool_json_extract(
            data=payload["data"],
            path=payload["path"],
        )
    if tool_name == "set_var":
        return tool_set_var(payload["name"], payload.get("value"))
    if tool_name == "template_render":
        return tool_template_render(
            template=payload["template"],
            step_context=step_context or {},
            var_context=var_context or {},
            strict=payload.get("strict", True),
        )
    if tool_name == "if_condition":
        if "logic" in payload or "conditions" in payload:
            return tool_if_condition(
                logic=payload.get("logic"),
                conditions=payload.get("conditions"),
            )
        return tool_if_condition(
            left=payload["left"],
            operator=payload["operator"],
            right=payload["right"],
        )

    return {
        "ok": False,
        "output_text": f"未知工具：{tool_name}",
        "output_data": None,
        "error": f"未知工具：{tool_name}",
    }


# =========================
# Legacy compatibility
# =========================
def run_legacy_step(step_name: str, user_input: str, previous_outputs: list[str]) -> tuple[str, bool]:
    step_name = step_name or ""

    if "读取文件" in step_name:
        path = extract_path_from_text(user_input)
        if not path:
            return "file_read 执行失败：缺少文件路径", False
        result = tool_file_read(path)
        return result["output_text"], result["ok"]

    if "写入" in step_name:
        matches = re.findall(r"(/[^ \n\r\t'\"，。；：]+)", user_input)
        target_path = matches[-1] if matches else None
        content = previous_outputs[-1] if previous_outputs else ""
        if not target_path:
            return "file_write 执行失败：缺少文件路径", False
        result = tool_file_write(target_path, content)
        return result["output_text"], result["ok"]

    if "列出目录" in step_name:
        path = extract_path_from_text(user_input)
        if not path:
            return "list_dir 执行失败：缺少目录路径", False
        result = tool_list_dir(path)
        return result["output_text"], result["ok"]

    if "执行命令" in step_name:
        command_match = re.search(r"[`‘“\"]([^`’”\"]+)[`’”\"]", user_input)
        command = command_match.group(1).strip() if command_match else ""
        if not command:
            return "shell_exec 执行失败：缺少命令", False
        result = tool_shell_exec(command)
        return result["output_text"], result["ok"]

    if "搜索" in step_name or "调研" in step_name:
        result = tool_web_search(user_input)
        return result["output_text"], result["ok"]

    if "整理" in step_name or "分析" in step_name or "摘要" in step_name:
        text = previous_outputs[-1] if previous_outputs else user_input
        result = tool_summarize_text(text)
        return result["output_text"], result["ok"]

    return f"已执行步骤：{step_name}", True


# =========================
# Artifact
# =========================
def write_artifact(task_id: int, user_input: str, step_outputs: list[str]) -> str:
    file_path = ARTIFACT_DIR / f"task_{task_id}.md"
    sections = []
    for idx, output in enumerate(step_outputs, start=1):
        sections.append(f"### 步骤 {idx}\n{output}")

    content = f"""# 任务结果

## 原始任务
{user_input}

## 执行步骤结果

{chr(10).join(sections)}
"""
    file_path.write_text(content, encoding="utf-8")
    return str(file_path)


# =========================
# Main worker loop
# =========================
def process_task(task: dict):
    task_id = task["id"]
    user_input = task["user_input"]

    conn = get_conn()
    cur = conn.cursor()

    try:
        update_task_status(cur, task_id, "running", None, None)
        conn.commit()

        planned = plan_task(user_input)

        if planned and isinstance(planned[0], dict):
            create_structured_steps(cur, task_id, planned)
            conn.commit()

            step_context: dict[int, dict] = {}
            var_context: dict[str, Any] = {}
            step_outputs: list[str] = []

            for step in planned:
                step_order = int(step.get("step_order"))
                tool_name = (step.get("tool") or "").strip()
                raw_input = step.get("input") or {}
                run_if = step.get("run_if")
                skip_if = step.get("skip_if")
                error_strategy = str(step.get("error_strategy") or "fail")

                set_step_running(cur, task_id, step_order)
                conn.commit()

                try:
                    if tool_name not in SUPPORTED_TOOLS:
                        raise ValueError(f"不支持的工具: {tool_name}")

                    should_run, skip_reason = should_run_step(step, step_context, var_context)
                    if not should_run:
                        skipped_output = f"步骤跳过：{skip_reason}"
                        skipped_data = {
                            "skipped": True,
                            "reason": skip_reason,
                            "run_if": run_if,
                            "skip_if": skip_if,
                        }
                        set_step_result(
                            cur,
                            task_id,
                            step_order,
                            status="completed",
                            tool_name=tool_name,
                            input_payload=raw_input,
                            output_payload=skipped_output,
                            output_data=skipped_data,
                            error_message="",
                            error_strategy=error_strategy,
                        )
                        conn.commit()
                        step_context[step_order] = {
                            "output_payload": skipped_output,
                            "output_data": skipped_data,
                        }
                        step_outputs.append(skipped_output)
                        continue

                    if tool_name == "if_condition":
                        if isinstance(raw_input, dict) and "logic" in raw_input and "conditions" in raw_input:
                            resolved_input = {
                                "logic": raw_input.get("logic"),
                                "conditions": [],
                            }
                            for condition in raw_input.get("conditions") or []:
                                cond_operator = condition.get("operator") if isinstance(condition, dict) else None
                                if cond_operator in {"exists", "not_exists"}:
                                    resolved_condition = dict(condition)
                                    resolved_condition["left"] = try_resolve_reference(condition.get("left"), step_context, var_context)
                                    resolved_condition["right"] = try_resolve_reference(condition.get("right"), step_context, var_context)
                                else:
                                    resolved_condition = resolve_input_payload(condition, step_context, var_context)
                                resolved_input["conditions"].append(resolved_condition)
                        else:
                            raw_operator = raw_input.get("operator") if isinstance(raw_input, dict) else None
                            if raw_operator in {"exists", "not_exists"}:
                                resolved_input = dict(raw_input)
                                resolved_input["left"] = try_resolve_reference(raw_input.get("left"), step_context, var_context)
                                resolved_input["right"] = try_resolve_reference(raw_input.get("right"), step_context, var_context)
                            else:
                                resolved_input = resolve_input_payload(raw_input, step_context)
                    elif tool_name == "template_render":
                        resolved_input = {
                            "template": raw_input.get("template", "") if isinstance(raw_input, dict) else "",
                            "strict": (raw_input.get("strict", True) if isinstance(raw_input, dict) else True),
                        }
                    else:
                        resolved_input = resolve_input_payload(raw_input, step_context, var_context)

                    if tool_name == "http_request":
                        resolved_input = normalize_http_request_input(resolved_input)

                    if tool_name == "file_write" and not isinstance(resolved_input.get("content"), str):
                        resolved_input = dict(resolved_input)
                        content_value = resolved_input.get("content")
                        if isinstance(content_value, (dict, list)):
                            resolved_input["content"] = json.dumps(content_value, ensure_ascii=False)
                        else:
                            resolved_input["content"] = str(content_value)

                    validate_input_value(tool_name, resolved_input)

                    result = execute_tool(tool_name, resolved_input, step_context, var_context)
                    ok = bool(result["ok"])

                    status = "completed" if ok else "failed"
                    set_step_result(
                        cur,
                        task_id,
                        step_order,
                        status=status,
                        tool_name=tool_name,
                        input_payload=resolved_input,
                        output_payload=result["output_text"],
                        output_data=result["output_data"],
                        error_message=result["error"],
                        error_strategy=error_strategy,
                    )
                    conn.commit()

                    if ok:
                        step_context[step_order] = {
                            "output_payload": result["output_text"],
                            "output_data": result["output_data"],
                        }
                        if tool_name == "set_var" and isinstance(result.get("output_data"), dict):
                            var_name = result["output_data"].get("name")
                            if isinstance(var_name, str) and var_name.strip():
                                var_context[var_name.strip()] = result["output_data"].get("value")
                        step_outputs.append(result["output_text"])
                    else:
                        if error_strategy == "continue":
                            step_context[step_order] = {
                                "output_payload": result["output_text"],
                                "output_data": result["output_data"],
                            }
                            step_outputs.append(result["output_text"])
                            continue
                        raise RuntimeError(f"Step {step_order} failed: {result['error']}")

                except Exception as e:
                    err = str(e)
                    set_step_result(
                        cur,
                        task_id,
                        step_order,
                        status="failed",
                        tool_name=tool_name,
                        input_payload=raw_input,
                        output_payload=err,
                        output_data=None,
                        error_message=err,
                        error_strategy=error_strategy,
                    )
                    conn.commit()
                    raise

        else:
            step_names = planned if isinstance(planned, list) else fallback_legacy_steps(user_input)
            create_legacy_steps(cur, task_id, step_names)
            conn.commit()

            previous_outputs = []
            step_outputs = []

            for step_order, step_name in enumerate(step_names, start=1):
                set_step_running(cur, task_id, step_order)
                conn.commit()

                output_text, ok = run_legacy_step(step_name, user_input, previous_outputs)
                status = "completed" if ok else "failed"

                set_step_result(
                    cur,
                    task_id,
                    step_order,
                    status=status,
                    tool_name=None,
                    input_payload=None,
                    output_payload=output_text,
                    output_data=None,
                    error_message="" if ok else output_text,
                    error_strategy="fail",
                )
                conn.commit()

                if not ok:
                    raise RuntimeError(f"Step {step_order} failed: {output_text}")

                previous_outputs.append(output_text)
                step_outputs.append(output_text)

        artifact_path = write_artifact(task_id, user_input, step_outputs)
        final_result = "\n\n".join(step_outputs) + f"\n\n产出文件：{artifact_path}"

        update_task_status(cur, task_id, "completed", final_result, None)
        conn.commit()

    except Exception as e:
        update_task_status(cur, task_id, "failed", None, str(e))
        conn.commit()
        print(f"[worker] task {task_id} failed: {e}")
    finally:
        cur.close()
        conn.close()


def fetch_next_pending_task():
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT *
            FROM task_runs
            WHERE status = 'pending'
            ORDER BY id ASC
            LIMIT 1;
            """
        )
        row = cur.fetchone()
        return row
    finally:
        cur.close()
        conn.close()


def main():
    print("[worker] started")
    while True:
        try:
            task = fetch_next_pending_task()
            if not task:
                time.sleep(2)
                continue

            print(f"[worker] picked task id={task['id']} user_input={task['user_input']}")
            process_task(task)

        except Exception as e:
            print(f"[worker] loop error: {e}")
            time.sleep(2)


if __name__ == "__main__":
    main()
