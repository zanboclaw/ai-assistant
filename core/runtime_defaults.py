import os
from typing import Any


SUPPORTED_TOOLS = (
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
)

APPROVAL_REQUIRED_TOOLS = (
    "shell_exec",
    "file_write",
    "write_json",
)

_RISK_POLICY_ENTRIES = (
    {
        "policy_key": "approval_low_risk_write_extensions",
        "value_type": "json",
        "policy_value": [".txt", ".md", ".csv", ".log"],
        "description": "新建这些扩展名的文件时可直接写入，无需审批。",
    },
    {
        "policy_key": "approval_sensitive_write_extensions",
        "value_type": "json",
        "policy_value": [
            ".py",
            ".sh",
            ".bash",
            ".zsh",
            ".env",
            ".json",
            ".yaml",
            ".yml",
            ".toml",
            ".ini",
            ".cfg",
            ".conf",
            ".sql",
        ],
        "description": "写入这些脚本/配置类扩展名时必须审批。",
    },
    {
        "policy_key": "approval_sensitive_write_basenames",
        "value_type": "json",
        "policy_value": ["dockerfile", "makefile", ".env", ".gitignore"],
        "description": "写入这些特定文件名时必须审批。",
    },
    {
        "policy_key": "approval_require_for_existing_file_overwrite",
        "value_type": "bool",
        "policy_value": True,
        "description": "覆盖已有文件时是否要求审批。",
    },
    {
        "policy_key": "approval_require_for_hidden_files",
        "value_type": "bool",
        "policy_value": True,
        "description": "写入隐藏文件时是否要求审批。",
    },
    {
        "policy_key": "approval_allowed_http_methods",
        "value_type": "json",
        "policy_value": ["GET"],
        "description": "这些 HTTP 方法默认允许直通，其余方法要求审批。",
    },
    {
        "policy_key": "approval_http_get_requires_approval_suffixes",
        "value_type": "json",
        "policy_value": [".local"],
        "description": "GET 请求命中这些域名后缀时仍要求审批。",
    },
)


def get_default_risk_policy_entries() -> list[dict[str, Any]]:
    return [
        {
            "policy_key": item["policy_key"],
            "value_type": item["value_type"],
            "policy_value": list(item["policy_value"]) if isinstance(item["policy_value"], list) else item["policy_value"],
            "description": item["description"],
        }
        for item in _RISK_POLICY_ENTRIES
    ]


def get_default_risk_policy_settings() -> dict[str, Any]:
    return {
        item["policy_key"]: (
            list(item["policy_value"]) if isinstance(item["policy_value"], list) else item["policy_value"]
        )
        for item in _RISK_POLICY_ENTRIES
    }


_TOOL_REGISTRY_ENTRIES = (
    {"tool_name": "file_read", "enabled": True, "provider_type": "builtin", "transport": "local", "server_name": "", "provider_config": {}, "risk_level": "low", "approval_required": False, "description": "读取文本文件。"},
    {"tool_name": "file_write", "enabled": True, "provider_type": "builtin", "transport": "local", "server_name": "", "provider_config": {}, "risk_level": "high", "approval_required": False, "description": "写入文本文件。"},
    {"tool_name": "list_dir", "enabled": True, "provider_type": "builtin", "transport": "local", "server_name": "", "provider_config": {}, "risk_level": "low", "approval_required": False, "description": "列出目录内容。"},
    {"tool_name": "shell_exec", "enabled": True, "provider_type": "builtin", "transport": "local", "server_name": "", "provider_config": {}, "risk_level": "high", "approval_required": False, "description": "执行受限 shell 命令。"},
    {"tool_name": "summarize_text", "enabled": True, "provider_type": "builtin", "transport": "local", "server_name": "", "provider_config": {}, "risk_level": "low", "approval_required": False, "description": "整理文本摘要。"},
    {"tool_name": "web_search", "enabled": True, "provider_type": "builtin", "transport": "local", "server_name": "", "provider_config": {}, "risk_level": "low", "approval_required": False, "description": "执行联网搜索。"},
    {"tool_name": "read_json", "enabled": True, "provider_type": "builtin", "transport": "local", "server_name": "", "provider_config": {}, "risk_level": "low", "approval_required": False, "description": "读取 JSON 文件。"},
    {"tool_name": "write_json", "enabled": True, "provider_type": "builtin", "transport": "local", "server_name": "", "provider_config": {}, "risk_level": "high", "approval_required": False, "description": "写入 JSON 文件。"},
    {"tool_name": "http_request", "enabled": True, "provider_type": "builtin", "transport": "local", "server_name": "", "provider_config": {}, "risk_level": "medium", "approval_required": False, "description": "执行 HTTP 请求。"},
    {"tool_name": "json_extract", "enabled": True, "provider_type": "builtin", "transport": "local", "server_name": "", "provider_config": {}, "risk_level": "low", "approval_required": False, "description": "从 JSON 中提取字段。"},
    {"tool_name": "if_condition", "enabled": True, "provider_type": "builtin", "transport": "local", "server_name": "", "provider_config": {}, "risk_level": "low", "approval_required": False, "description": "执行条件判断。"},
    {"tool_name": "set_var", "enabled": True, "provider_type": "builtin", "transport": "local", "server_name": "", "provider_config": {}, "risk_level": "low", "approval_required": False, "description": "写入运行时变量。"},
    {"tool_name": "template_render", "enabled": True, "provider_type": "builtin", "transport": "local", "server_name": "", "provider_config": {}, "risk_level": "low", "approval_required": False, "description": "渲染文本模板。"},
)


def get_default_tool_registry_entries() -> list[dict[str, Any]]:
    return [dict(item) for item in _TOOL_REGISTRY_ENTRIES]


def get_default_tool_registry_settings() -> dict[str, dict[str, Any]]:
    return {
        item["tool_name"]: {
            "enabled": item["enabled"],
            "provider_type": item.get("provider_type", "builtin"),
            "transport": item.get("transport", "local"),
            "server_name": item.get("server_name", ""),
            "provider_config": dict(item.get("provider_config") or {}),
            "risk_level": item["risk_level"],
            "approval_required": bool(item.get("approval_required", False)),
            "description": item["description"],
        }
        for item in _TOOL_REGISTRY_ENTRIES
    }


def _planner_model_name() -> str:
    return os.environ.get("DEEPSEEK_PLANNER_MODEL", os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"))


def _summary_model_name() -> str:
    return os.environ.get("DEEPSEEK_SUMMARY_MODEL", os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"))


def _search_summary_model_name() -> str:
    return os.environ.get("DEEPSEEK_SEARCH_SUMMARY_MODEL", os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"))


def _deepseek_base_url() -> str:
    return os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")


_MODEL_ROUTE_DEFINITIONS = (
    {
        "route_name": "planner",
        "provider": "deepseek_default",
        "model_name_fn": _planner_model_name,
        "temperature": 0.2,
        "max_tokens": 1500,
        "enabled": True,
        "description": "任务规划模型路由。",
    },
    {
        "route_name": "summarize_text",
        "provider": "deepseek_default",
        "model_name_fn": _summary_model_name,
        "temperature": 0.2,
        "max_tokens": 800,
        "enabled": True,
        "description": "文本摘要模型路由。",
    },
    {
        "route_name": "web_search_summary",
        "provider": "deepseek_default",
        "model_name_fn": _search_summary_model_name,
        "temperature": 0.2,
        "max_tokens": 1200,
        "enabled": True,
        "description": "搜索结果整理模型路由。",
    },
)


def get_default_model_route_entries() -> list[dict[str, Any]]:
    return [
        {
            "route_name": item["route_name"],
            "provider": item["provider"],
            "model_name": item["model_name_fn"](),
            "temperature": item["temperature"],
            "max_tokens": item["max_tokens"],
            "enabled": item["enabled"],
            "description": item["description"],
        }
        for item in _MODEL_ROUTE_DEFINITIONS
    ]


def get_default_model_route_settings() -> dict[str, dict[str, Any]]:
    return {
        item["route_name"]: {
            "provider": item["provider"],
            "model_name": item["model_name_fn"](),
            "temperature": item["temperature"],
            "max_tokens": item["max_tokens"],
            "enabled": item["enabled"],
        }
        for item in _MODEL_ROUTE_DEFINITIONS
    }


_MODEL_PROVIDER_DEFINITIONS = (
    {
        "provider_name": "deepseek_default",
        "driver": "openai_compatible",
        "base_url_fn": _deepseek_base_url,
        "api_key_env_fn": lambda: "DEEPSEEK_API_KEY",
        "enabled": True,
        "description": "默认 DeepSeek OpenAI-compatible provider。",
    },
    {
        "provider_name": "openai_compatible",
        "driver": "openai_compatible",
        "base_url_fn": lambda: os.environ.get("OPENAI_COMPATIBLE_BASE_URL", _deepseek_base_url()),
        "api_key_env_fn": lambda: os.environ.get("OPENAI_COMPATIBLE_API_KEY_ENV", "DEEPSEEK_API_KEY"),
        "enabled": True,
        "description": "兼容历史 route.provider 的默认 OpenAI-compatible provider。",
    },
)


def get_default_model_provider_entries() -> list[dict[str, Any]]:
    return [
        {
            "provider_name": item["provider_name"],
            "driver": item["driver"],
            "base_url": item["base_url_fn"](),
            "api_key_env": item["api_key_env_fn"](),
            "enabled": item["enabled"],
            "description": item["description"],
        }
        for item in _MODEL_PROVIDER_DEFINITIONS
    ]


def get_default_model_provider_settings() -> dict[str, dict[str, Any]]:
    return {
        item["provider_name"]: {
            "driver": item["driver"],
            "base_url": item["base_url_fn"](),
            "api_key_env": item["api_key_env_fn"](),
            "enabled": item["enabled"],
        }
        for item in _MODEL_PROVIDER_DEFINITIONS
    }
