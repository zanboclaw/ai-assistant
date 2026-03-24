from __future__ import annotations

import json
import re
from typing import Any

from core.task_runtime import build_task_display_user_input


PLANNER_MEMORY_CONTEXT_HEADING = "可复用的长期记忆："
WEB_SEARCH_QUERY_MAX_LENGTH = 240


def parse_jsonish(value: Any, default: Any):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return default
        try:
            return json.loads(text)
        except Exception:
            return default
    return default


def normalize_runtime_overrides(value: Any) -> dict[str, Any]:
    parsed = parse_jsonish(value, {})
    return parsed if isinstance(parsed, dict) else {}


def extract_task_model_route_overrides(task_row: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    runtime_overrides = normalize_runtime_overrides((task_row or {}).get("runtime_overrides"))
    raw_overrides = runtime_overrides.get("model_route_overrides") or {}
    if not isinstance(raw_overrides, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for route_name, config in raw_overrides.items():
        normalized_route_name = str(route_name or "").strip()
        if not normalized_route_name or not isinstance(config, dict):
            continue
        normalized[normalized_route_name] = dict(config)
    return normalized


def extract_task_skill_invocation(task_row: dict[str, Any] | None) -> dict[str, Any]:
    runtime_overrides = normalize_runtime_overrides((task_row or {}).get("runtime_overrides"))
    raw = runtime_overrides.get("skill_invocation") or {}
    return dict(raw) if isinstance(raw, dict) else {}


def extract_task_intent(task_row: dict[str, Any] | None) -> dict[str, Any]:
    raw = parse_jsonish((task_row or {}).get("task_intent_json"), {})
    return dict(raw) if isinstance(raw, dict) else {}


def extract_deliverable_spec(task_row: dict[str, Any] | None) -> dict[str, Any]:
    raw = parse_jsonish((task_row or {}).get("deliverable_spec_json"), {})
    return dict(raw) if isinstance(raw, dict) else {}


def extract_validation_report(task_row: dict[str, Any] | None) -> dict[str, Any]:
    raw = parse_jsonish((task_row or {}).get("validation_report_json"), {})
    return dict(raw) if isinstance(raw, dict) else {}


def extract_recovery_action(task_row: dict[str, Any] | None) -> dict[str, Any]:
    raw = parse_jsonish((task_row or {}).get("recovery_action_json"), {})
    return dict(raw) if isinstance(raw, dict) else {}


def build_task_display_input_excerpt(task_row: dict[str, Any], limit: int = 180) -> str:
    return build_task_display_user_input(
        str(task_row.get("user_input") or ""),
        normalize_runtime_overrides(task_row.get("runtime_overrides")),
    )[:limit]


def build_task_display_input(task_row: dict[str, Any]) -> str:
    return build_task_display_user_input(
        str(task_row.get("user_input") or ""),
        normalize_runtime_overrides(task_row.get("runtime_overrides")),
    )


def extract_memory_context(task_row: dict[str, Any] | None) -> dict[str, Any]:
    runtime_overrides = normalize_runtime_overrides((task_row or {}).get("runtime_overrides"))
    memory_context = runtime_overrides.get("memory_context") or {}
    return dict(memory_context) if isinstance(memory_context, dict) else {}


def build_planner_memory_context_text(memory_context: dict[str, Any] | None) -> str:
    retrieved_memories = list((memory_context or {}).get("retrieved_memories") or [])
    if not retrieved_memories:
        return ""

    lines = ["可复用的长期记忆："]
    for index, item in enumerate(retrieved_memories[:4], start=1):
        memory_kind = str(item.get("memory_kind") or "memory").strip()
        title = str(item.get("title") or "").strip()
        content = str(item.get("content") or "").strip()
        summary = content[:220] + ("..." if len(content) > 220 else "")
        line = f"{index}. [{memory_kind}]"
        if title:
            line += f" {title}"
        if summary:
            line += f" -> {summary}"
        lines.append(line)
    return "\n".join(lines)


def strip_augmented_memory_context(user_input: str) -> str:
    normalized_user_input = str(user_input or "").strip()
    if not normalized_user_input:
        return ""

    marker = f"\n\n{PLANNER_MEMORY_CONTEXT_HEADING}"
    if marker in normalized_user_input:
        return normalized_user_input.split(marker, 1)[0].strip()
    if normalized_user_input.startswith(PLANNER_MEMORY_CONTEXT_HEADING):
        return ""
    return normalized_user_input


def sanitize_web_search_query(query: str, limit: int = WEB_SEARCH_QUERY_MAX_LENGTH) -> str:
    base_query = strip_augmented_memory_context(query)
    normalized_query = re.sub(r"\s+", " ", base_query).strip()
    if not normalized_query:
        normalized_query = re.sub(r"\s+", " ", str(query or "")).strip()
    if limit <= 0 or len(normalized_query) <= limit:
        return normalized_query
    return normalized_query[:limit].rstrip(" ,.;:!?\u3002\uff0c\uff1b\uff1a")


def augment_user_input_with_memory_context(user_input: str, task_row: dict[str, Any] | None) -> str:
    memory_context_text = build_planner_memory_context_text(extract_memory_context(task_row))
    normalized_user_input = str(user_input or "").strip()
    if not memory_context_text:
        return normalized_user_input
    if not normalized_user_input:
        return memory_context_text
    return f"{normalized_user_input}\n\n{memory_context_text}"
