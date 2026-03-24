from __future__ import annotations

import json
from typing import Any, Optional


def validate_shell_command(
    command: str,
    *,
    shlex_module,
    safe_commands: set[str],
    disallowed_tokens: set[str],
):
    stripped = command.strip()
    if not stripped:
        raise ValueError("缺少命令")

    tokens = shlex_module.split(stripped)
    if not tokens:
        raise ValueError("命令解析失败")

    first = tokens[0]
    if first not in safe_commands:
        raise ValueError(f"命令不在白名单中 -> {first}")

    for token in tokens:
        if token in disallowed_tokens:
            raise ValueError(f"命令包含禁用词 -> {token}")

    return tokens


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


def summarize_search_results(
    query: str,
    results: list[dict],
    *,
    get_model_route_config,
    serialize_model_route_runtime_info,
    get_model_provider_client,
    record_model_trace,
    safe_json_dumps,
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    if not results:
        return f"未找到可摘要的搜索结果。查询词：{query}", {
            "summary_backend": "no_results",
            "summary_model_route": {},
        }

    simplified_results = []
    for item in results[:5]:
        simplified_results.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": (item.get("content", "") or "")[:300],
            }
        )

    route_info: dict[str, Any] = {}
    try:
        route = get_model_route_config("web_search_summary", route_overrides=model_route_overrides)
        route_info = serialize_model_route_runtime_info("web_search_summary", route)
        client = get_model_provider_client(str(route["provider"]))
        prompt_version = "web_search_summary-v1"
        request_payload = json.dumps(
            {"query": query, "results": simplified_results},
            ensure_ascii=False,
        )
        completion = client.chat.completions.create(
            model=str(route["model_name"]),
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
                    "content": request_payload,
                },
            ],
            temperature=float(route["temperature"]),
            max_tokens=int(route["max_tokens"]),
        )
        text = (completion.choices[0].message.content or "").strip()
        if text:
            record_model_trace(
                route_name="web_search_summary",
                provider=str(route["provider"]),
                model_name=str(route["model_name"]),
                prompt_version=prompt_version,
                prompt_text=request_payload,
                response_text=text,
                status="completed",
                metadata=route_info,
            )
            return text, {
                "summary_backend": "model",
                "summary_model_route": route_info,
            }
    except Exception as exc:
        if route_info:
            record_model_trace(
                route_name="web_search_summary",
                provider=str(route_info.get("provider") or ""),
                model_name=str(route_info.get("model_name") or ""),
                prompt_version="web_search_summary-v1",
                prompt_text=query,
                status="failed",
                error_summary=str(exc),
                metadata=route_info,
            )

    lines = ["### 结论摘要"]
    lines.append(f"- 针对查询“{query}”获取到 {len(results[:5])} 条候选结果。")
    lines.append("")
    lines.append("### 关键来源")
    for item in results[:5]:
        lines.append(f"- {item.get('title', '')}")
        lines.append(f"  {item.get('url', '')}")
    return "\n".join(lines), {
        "summary_backend": "fallback_heuristic",
        "summary_model_route": route_info,
    }


def web_search_duckduckgo(
    query: str,
    *,
    requests_module,
    beautiful_soup_cls,
    summarize_search_results_fn,
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    url = "https://html.duckduckgo.com/html/"
    headers = {"User-Agent": "Mozilla/5.0"}

    resp = requests_module.post(
        url,
        data={"q": query},
        headers=headers,
        timeout=8,
    )
    resp.raise_for_status()

    soup = beautiful_soup_cls(resp.text, "html.parser")
    parsed_results = []

    for link in soup.select(".result__title a")[:8]:
        title = link.get_text(" ", strip=True)
        href = link.get("href", "")
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
        return f"web_search 已执行，但没有找到明显结果。查询词：{query}", {
            "search_provider": "duckduckgo",
            "result_count": 0,
            "summary_backend": "no_results",
            "summary_model_route": {},
        }

    summary, summary_metadata = summarize_search_results_fn(
        query,
        parsed_results,
        model_route_overrides=model_route_overrides,
    )

    raw_refs = []
    for item in parsed_results:
        raw_refs.append(f"- {item['title']}\n  {item['url']}")

    return (
        "web_search 结果（DuckDuckGo）\n\n"
        f"{summary}\n\n"
        "原始来源：\n" + "\n".join(raw_refs)
    ), {
        "search_provider": "duckduckgo",
        "result_count": len(parsed_results),
        **summary_metadata,
    }


def web_search_tavily(
    query: str,
    *,
    requests_module,
    tavily_api_key: str | None,
    summarize_search_results_fn,
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    if not tavily_api_key:
        raise ValueError("DuckDuckGo 不可用，且缺少 TAVILY_API_KEY")

    url = "https://api.tavily.com/search"
    headers = {"Content-Type": "application/json"}
    payload = {
        "api_key": tavily_api_key,
        "query": query,
        "search_depth": "basic",
        "max_results": 8,
        "include_answer": False,
        "include_raw_content": False,
    }

    resp = requests_module.post(url, headers=headers, json=payload, timeout=15)
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
        return f"web_search 已执行，但没有找到明显结果。查询词：{query}", {
            "search_provider": "tavily",
            "result_count": 0,
            "summary_backend": "no_results",
            "summary_model_route": {},
        }

    summary, summary_metadata = summarize_search_results_fn(
        query,
        parsed_results,
        model_route_overrides=model_route_overrides,
    )

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
    ), {
        "search_provider": "tavily",
        "result_count": len(parsed_results),
        **summary_metadata,
    }


def tool_web_search(
    query: str,
    *,
    web_search_duckduckgo_fn,
    web_search_tavily_fn,
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict:
    try:
        try:
            text, search_metadata = web_search_duckduckgo_fn(
                query,
                model_route_overrides=model_route_overrides,
            )
        except Exception:
            text, search_metadata = web_search_tavily_fn(
                query,
                model_route_overrides=model_route_overrides,
            )

        return {
            "ok": True,
            "output_text": text,
            "output_data": {
                "query": query,
                "text": text,
                **search_metadata,
            },
            "error": "",
        }
    except Exception as exc:
        msg = f"web_search 执行失败：{exc}"
        return {
            "ok": False,
            "output_text": msg,
            "output_data": None,
            "error": msg,
        }


def _normalize_mcp_tool_result(response_data: Any, *, safe_json_dumps) -> dict:
    if isinstance(response_data, dict):
        ok = bool(response_data.get("ok", True))
        output_text = str(
            response_data.get("output_text")
            or response_data.get("text")
            or response_data.get("content")
            or ""
        )
        output_data = response_data.get("output_data")
        if output_data is None:
            output_data = response_data.get("data")
        error_text = str(response_data.get("error") or "")
        if not output_text:
            output_text = safe_json_dumps(response_data)
        return {
            "ok": ok,
            "output_text": output_text,
            "output_data": output_data,
            "error": error_text if not ok else "",
        }

    if isinstance(response_data, str):
        return {
            "ok": True,
            "output_text": response_data,
            "output_data": {"text": response_data},
            "error": "",
        }

    return {
        "ok": True,
        "output_text": safe_json_dumps(response_data),
        "output_data": response_data,
        "error": "",
    }


def execute_mcp_tool(
    tool_name: str,
    payload: dict,
    registry_entry: dict[str, Any],
    *,
    shlex_module,
    subprocess_module,
    requests_module,
    safe_json_dumps,
    env: dict[str, str],
) -> dict:
    provider_type = str(registry_entry.get("provider_type") or "").strip().lower()
    provider_config = registry_entry.get("provider_config") or {}
    timeout_seconds = int(provider_config.get("timeout") or 15)
    request_payload = {
        "tool_name": tool_name,
        "arguments": payload,
        "server_name": str(registry_entry.get("server_name") or ""),
    }

    try:
        if provider_type == "mcp_stdio":
            command = provider_config.get("command")
            if isinstance(command, str):
                command = shlex_module.split(command)
            if not isinstance(command, list) or not command or not all(isinstance(item, str) and item.strip() for item in command):
                raise ValueError(f"{tool_name} 的 mcp_stdio command 非法")

            merged_env = dict(env)
            extra_env = provider_config.get("env") or {}
            if isinstance(extra_env, dict):
                merged_env.update({str(key): str(value) for key, value in extra_env.items()})

            proc = subprocess_module.run(
                command,
                input=safe_json_dumps(request_payload),
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                env=merged_env,
            )
            if proc.returncode != 0:
                stderr = (proc.stderr or proc.stdout or "").strip()
                raise RuntimeError(stderr or f"mcp_stdio exited with code {proc.returncode}")
            response_text = (proc.stdout or "").strip()
            if not response_text:
                raise RuntimeError("mcp_stdio returned empty stdout")
            try:
                response_data = json.loads(response_text)
            except Exception:
                response_data = {"ok": True, "output_text": response_text, "output_data": {"raw_stdout": response_text}}
            return _normalize_mcp_tool_result(response_data, safe_json_dumps=safe_json_dumps)

        if provider_type == "mcp_http":
            url = str(provider_config.get("url") or "").strip()
            if not url:
                raise ValueError(f"{tool_name} 的 mcp_http url 不能为空")
            method = str(provider_config.get("method") or "POST").upper().strip()
            headers = provider_config.get("headers") if isinstance(provider_config.get("headers"), dict) else {}
            if method == "GET":
                response = requests_module.get(url, params=request_payload, headers=headers, timeout=timeout_seconds)
            else:
                response = requests_module.post(url, json=request_payload, headers=headers, timeout=timeout_seconds)
            response.raise_for_status()
            content_type = str(response.headers.get("Content-Type") or "").lower()
            if "application/json" in content_type:
                response_data = response.json()
            else:
                response_data = {"ok": True, "output_text": response.text, "output_data": {"text": response.text}}
            return _normalize_mcp_tool_result(response_data, safe_json_dumps=safe_json_dumps)

        raise ValueError(f"不支持的 MCP provider_type: {provider_type or '(empty)'}")
    except Exception as exc:
        message = f"{tool_name} MCP 执行失败：{exc}"
        return {
            "ok": False,
            "output_text": message,
            "output_data": None,
            "error": message,
        }


def is_private_ip(ip_str: str, *, ipaddress_module) -> bool:
    ip = ipaddress_module.ip_address(ip_str)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def resolve_hostname_ips(hostname: str, *, socket_module) -> list[str]:
    ips = []
    try:
        infos = socket_module.getaddrinfo(hostname, None)
        for info in infos:
            sockaddr = info[4]
            if sockaddr:
                ip = sockaddr[0]
                if ip not in ips:
                    ips.append(ip)
    except Exception:
        pass
    return ips


def validate_http_url(
    url: str,
    *,
    urlparse_fn,
    ipaddress_module,
    resolve_hostname_ips_fn,
    blocked_hosts: set[str],
):
    parsed = urlparse_fn(url)

    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"不支持的 URL 协议 -> {parsed.scheme}")

    if not parsed.netloc:
        raise ValueError("URL 非法，缺少 host")

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise ValueError("URL 非法，缺少 hostname")

    if hostname in blocked_hosts:
        raise ValueError(f"禁止访问内网或本机地址 -> {hostname}")

    try:
        ip = ipaddress_module.ip_address(hostname)
        if is_private_ip(str(ip), ipaddress_module=ipaddress_module):
            raise ValueError(f"禁止访问内网或本机地址 -> {hostname}")
    except ValueError:
        pass

    ips = resolve_hostname_ips_fn(hostname)
    if not ips:
        raise ValueError(f"无法解析域名 -> {hostname}")

    for ip_str in ips:
        if is_private_ip(ip_str, ipaddress_module=ipaddress_module):
            raise ValueError(f"禁止访问内网或本机地址 -> {hostname} -> {ip_str}")


def tool_http_request(
    url: str,
    method: str,
    *,
    validate_http_url_fn,
    requests_module,
    params: Optional[dict] = None,
    json_body: Optional[dict] = None,
    timeout: int = 15,
) -> dict:
    try:
        validate_http_url_fn(url)

        method = method.upper().strip()
        if method not in {"GET", "POST"}:
            raise ValueError(f"不支持的 method -> {method}")

        if timeout <= 0 or timeout > 20:
            raise ValueError("timeout 必须在 1 到 20 秒之间")

        headers = {
            "User-Agent": "AI-Assistant-Worker/1.0"
        }

        if method == "GET":
            response = requests_module.get(
                url,
                params=params or {},
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
            )
        else:
            response = requests_module.post(
                url,
                json=json_body or {},
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
            )

        content_type = response.headers.get("Content-Type", "")
        text = response.text[:5000]

        parsed_json = None
        if "application/json" in content_type.lower():
            try:
                parsed_json = response.json()
            except Exception:
                parsed_json = None

        preview = text[:1000]
        output_text = (
            f"http_request 成功：{method} {response.url}\n"
            f"状态码：{response.status_code}\n"
            f"Content-Type：{content_type}\n"
            f"响应预览：\n{preview if preview else '(空)'}"
        )

        return {
            "ok": True,
            "output_text": output_text,
            "output_data": {
                "url": str(response.url),
                "method": method,
                "status_code": response.status_code,
                "content_type": content_type,
                "text": text,
                "json": parsed_json,
            },
            "error": "",
        }

    except Exception as exc:
        msg = f"http_request 执行失败：{exc}"
        return {
            "ok": False,
            "output_text": msg,
            "output_data": None,
            "error": msg,
        }


def execute_tool(
    tool_name: str,
    payload: dict,
    *,
    get_tool_registry_entry,
    execute_mcp_tool_fn,
    tool_file_read_fn,
    tool_file_write_fn,
    tool_list_dir_fn,
    tool_shell_exec_fn,
    tool_generate_text_fn,
    tool_summarize_text_fn,
    tool_web_search_fn,
    tool_read_json_fn,
    tool_write_json_fn,
    tool_http_request_fn,
    tool_json_extract_fn,
    tool_set_var_fn,
    tool_template_render_fn,
    tool_if_condition_fn,
    step_context: Optional[dict[int, dict]] = None,
    var_context: Optional[dict[str, Any]] = None,
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict:
    registry_entry = get_tool_registry_entry(tool_name)
    if registry_entry and str(registry_entry.get("provider_type") or "builtin").strip().lower() in {"mcp_stdio", "mcp_http"}:
        return execute_mcp_tool_fn(tool_name, payload, registry_entry)
    if tool_name == "file_read":
        return tool_file_read_fn(payload["path"])
    if tool_name == "file_write":
        return tool_file_write_fn(payload["path"], payload["content"])
    if tool_name == "list_dir":
        return tool_list_dir_fn(payload["path"])
    if tool_name == "shell_exec":
        return tool_shell_exec_fn(payload["command"])
    if tool_name == "generate_text":
        return tool_generate_text_fn(
            payload["prompt"],
            system_prompt=str(payload.get("system_prompt") or ""),
            model_route_overrides=model_route_overrides,
        )
    if tool_name == "summarize_text":
        return tool_summarize_text_fn(
            payload["text"],
            model_route_overrides=model_route_overrides,
        )
    if tool_name == "web_search":
        return tool_web_search_fn(
            payload["query"],
            model_route_overrides=model_route_overrides,
        )
    if tool_name == "read_json":
        return tool_read_json_fn(payload["path"])
    if tool_name == "write_json":
        return tool_write_json_fn(payload["path"], payload["data"])
    if tool_name == "http_request":
        return tool_http_request_fn(
            url=payload["url"],
            method=payload["method"],
            params=payload.get("params"),
            json_body=payload.get("json"),
            timeout=payload.get("timeout", 15),
        )
    if tool_name == "json_extract":
        return tool_json_extract_fn(
            data=payload["data"],
            path=payload["path"],
        )
    if tool_name == "set_var":
        return tool_set_var_fn(payload["name"], payload.get("value"))
    if tool_name == "template_render":
        return tool_template_render_fn(
            template=payload["template"],
            step_context=step_context or {},
            var_context=var_context or {},
            strict=payload.get("strict", True),
        )
    if tool_name == "if_condition":
        if "logic" in payload or "conditions" in payload:
            return tool_if_condition_fn(
                logic=payload.get("logic"),
                conditions=payload.get("conditions"),
            )
        return tool_if_condition_fn(
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
