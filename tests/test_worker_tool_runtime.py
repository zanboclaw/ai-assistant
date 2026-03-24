import json
import shlex
from types import SimpleNamespace
from urllib.parse import urlparse

from tool_runtime import (
    dedupe_search_results,
    execute_mcp_tool,
    execute_tool,
    tool_http_request,
    tool_web_search,
    validate_http_url,
    validate_shell_command,
)


class FakeResponse:
    def __init__(self, *, text="", json_data=None, status_code=200, url="https://example.com", headers=None):
        self.text = text
        self._json_data = json_data
        self.status_code = status_code
        self.url = url
        self.headers = headers or {}

    def raise_for_status(self):
        return None

    def json(self):
        if isinstance(self._json_data, Exception):
            raise self._json_data
        return self._json_data


class FakeRequests:
    def __init__(self, *, get_response=None, post_response=None):
        self.get_response = get_response
        self.post_response = post_response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        return self.get_response

    def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        return self.post_response


def test_validate_shell_command_allows_safe_command_and_blocks_disallowed_token():
    tokens = validate_shell_command(
        "git status",
        shlex_module=shlex,
        safe_commands={"git", "ls"},
        disallowed_tokens={"rm"},
    )

    assert tokens == ["git", "status"]

    try:
        validate_shell_command(
            "git rm README.md",
            shlex_module=shlex,
            safe_commands={"git", "ls"},
            disallowed_tokens={"rm"},
        )
    except ValueError as exc:
        assert "禁用词" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected disallowed token to be rejected")


def test_dedupe_search_results_keeps_first_unique_url():
    deduped = dedupe_search_results(
        [
            {"title": "A", "url": "https://a.example.com"},
            {"title": "A2", "url": "https://a.example.com"},
            {"title": "B", "url": "https://b.example.com"},
            {"title": "Empty", "url": ""},
        ]
    )

    assert deduped == [
        {"title": "A", "url": "https://a.example.com"},
        {"title": "B", "url": "https://b.example.com"},
    ]


def test_tool_web_search_falls_back_to_tavily_when_duckduckgo_fails():
    result = tool_web_search(
        "最新发布流程",
        web_search_duckduckgo_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("ddg failed")),
        web_search_tavily_fn=lambda query, **_kwargs: (
            f"tavily:{query}",
            {"search_provider": "tavily", "result_count": 1},
        ),
    )

    assert result["ok"] is True
    assert result["output_data"]["search_provider"] == "tavily"
    assert result["output_text"] == "tavily:最新发布流程"


def test_validate_http_url_blocks_localhost_and_unresolved_host():
    for url in ("http://localhost:8000", "https://missing.example.com"):
        try:
            validate_http_url(
                url,
                urlparse_fn=urlparse,
                ipaddress_module=__import__("ipaddress"),
                resolve_hostname_ips_fn=lambda hostname: [] if hostname == "missing.example.com" else ["93.184.216.34"],
                blocked_hosts={"localhost"},
            )
        except ValueError as exc:
            assert "禁止访问" in str(exc) or "无法解析域名" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("expected URL validation failure")


def test_tool_http_request_returns_json_preview():
    requests_module = FakeRequests(
        get_response=FakeResponse(
            text='{"ok": true}',
            json_data={"ok": True},
            status_code=200,
            url="https://example.com/api",
            headers={"Content-Type": "application/json"},
        )
    )

    result = tool_http_request(
        "https://example.com/api",
        "GET",
        validate_http_url_fn=lambda _url: None,
        requests_module=requests_module,
        params={"q": "x"},
        timeout=8,
    )

    assert result["ok"] is True
    assert result["output_data"]["json"] == {"ok": True}
    assert requests_module.calls[0][0] == "get"


def test_execute_mcp_tool_supports_http_provider():
    requests_module = FakeRequests(
        post_response=FakeResponse(
            text='{"ok": true, "output_text": "done", "output_data": {"value": 1}}',
            json_data={"ok": True, "output_text": "done", "output_data": {"value": 1}},
            headers={"Content-Type": "application/json"},
        )
    )

    result = execute_mcp_tool(
        "remote_tool",
        {"x": 1},
        {
            "provider_type": "mcp_http",
            "provider_config": {"url": "https://mcp.example.com/exec"},
        },
        shlex_module=shlex,
        subprocess_module=SimpleNamespace(run=None),
        requests_module=requests_module,
        safe_json_dumps=lambda value: json.dumps(value, ensure_ascii=False),
        env={},
    )

    assert result["ok"] is True
    assert result["output_text"] == "done"
    assert result["output_data"] == {"value": 1}


def test_execute_tool_dispatches_http_request_and_unknown_tool():
    result = execute_tool(
        "http_request",
        {"url": "https://example.com", "method": "GET"},
        get_tool_registry_entry=lambda _tool_name: None,
        execute_mcp_tool_fn=lambda *_args: {"ok": True},
        tool_file_read_fn=lambda path: {"tool": "file_read", "path": path},
        tool_file_write_fn=lambda path, content: {"tool": "file_write", "path": path, "content": content},
        tool_list_dir_fn=lambda path: {"tool": "list_dir", "path": path},
        tool_shell_exec_fn=lambda command: {"tool": "shell_exec", "command": command},
        tool_generate_text_fn=lambda prompt, **kwargs: {"tool": "generate_text", "prompt": prompt, **kwargs},
        tool_summarize_text_fn=lambda text, **kwargs: {"tool": "summarize_text", "text": text, **kwargs},
        tool_web_search_fn=lambda query, **kwargs: {"tool": "web_search", "query": query, **kwargs},
        tool_read_json_fn=lambda path: {"tool": "read_json", "path": path},
        tool_write_json_fn=lambda path, data: {"tool": "write_json", "path": path, "data": data},
        tool_http_request_fn=lambda **kwargs: {"tool": "http_request", **kwargs},
        tool_json_extract_fn=lambda data, path: {"tool": "json_extract", "data": data, "path": path},
        tool_set_var_fn=lambda name, value: {"tool": "set_var", "name": name, "value": value},
        tool_template_render_fn=lambda **kwargs: {"tool": "template_render", **kwargs},
        tool_if_condition_fn=lambda **kwargs: {"tool": "if_condition", **kwargs},
    )

    assert result["tool"] == "http_request"
    assert result["url"] == "https://example.com"

    unknown = execute_tool(
        "missing_tool",
        {},
        get_tool_registry_entry=lambda _tool_name: None,
        execute_mcp_tool_fn=lambda *_args: {"ok": True},
        tool_file_read_fn=lambda path: {"tool": "file_read", "path": path},
        tool_file_write_fn=lambda path, content: {"tool": "file_write", "path": path, "content": content},
        tool_list_dir_fn=lambda path: {"tool": "list_dir", "path": path},
        tool_shell_exec_fn=lambda command: {"tool": "shell_exec", "command": command},
        tool_generate_text_fn=lambda prompt, **kwargs: {"tool": "generate_text", "prompt": prompt, **kwargs},
        tool_summarize_text_fn=lambda text, **kwargs: {"tool": "summarize_text", "text": text, **kwargs},
        tool_web_search_fn=lambda query, **kwargs: {"tool": "web_search", "query": query, **kwargs},
        tool_read_json_fn=lambda path: {"tool": "read_json", "path": path},
        tool_write_json_fn=lambda path, data: {"tool": "write_json", "path": path, "data": data},
        tool_http_request_fn=lambda **kwargs: {"tool": "http_request", **kwargs},
        tool_json_extract_fn=lambda data, path: {"tool": "json_extract", "data": data, "path": path},
        tool_set_var_fn=lambda name, value: {"tool": "set_var", "name": name, "value": value},
        tool_template_render_fn=lambda **kwargs: {"tool": "template_render", **kwargs},
        tool_if_condition_fn=lambda **kwargs: {"tool": "if_condition", **kwargs},
    )

    assert unknown["ok"] is False
    assert "未知工具" in unknown["error"]
