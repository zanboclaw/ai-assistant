from __future__ import annotations

import json
import re
from typing import Any

from core.task_runtime import build_task_display_user_input
from task_payloads import build_generation_user_input, sanitize_web_search_query


def count_markdown_heading(text: str, heading: str) -> int:
    if not text.strip() or not heading.strip():
        return 0
    pattern = rf"(?m)^#+\s*{re.escape(heading.strip())}\s*$"
    return len(re.findall(pattern, text))


def extract_markdown_section_bodies(text: str) -> dict[str, str]:
    normalized = str(text or "")
    if not normalized.strip():
        return {}
    pattern = re.compile(r"(?m)^#+\s*(.+?)\s*$")
    matches = list(pattern.finditer(normalized))
    if not matches:
        return {}

    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        title = str(match.group(1) or "").strip()
        if not title:
            continue
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        body = normalized[body_start:body_end].strip()
        sections[title] = body
    return sections


def extract_first_level_section_body(text: str, heading: str) -> str:
    normalized = str(text or "")
    target_heading = str(heading or "").strip()
    if not normalized.strip() or not target_heading:
        return ""

    collected_lines: list[str] = []
    collecting = False
    top_level_pattern = re.compile(r"^#(?!#)\s+(.+?)\s*$")

    for raw_line in normalized.splitlines():
        matched = top_level_pattern.match(raw_line.strip())
        if matched:
            current_heading = str(matched.group(1) or "").strip()
            if collecting:
                break
            collecting = current_heading == target_heading
            continue
        if collecting:
            collected_lines.append(raw_line)

    return "\n".join(collected_lines).strip()


def get_expected_section_body_lengths(text: str, expected_sections: list[str]) -> dict[str, int]:
    sections = extract_markdown_section_bodies(text)
    results: dict[str, int] = {}
    for expected in expected_sections:
        expected_title = str(expected or "").strip()
        if not expected_title:
            continue
        results[expected_title] = len(sections.get(expected_title, "").strip())
    return results


def count_markdown_subheadings(text: str) -> int:
    normalized = str(text or "")
    if not normalized.strip():
        return 0
    return len(re.findall(r"(?m)^#{2,6}\s+.+\S.*$", normalized))


def count_structured_section_items(text: str) -> int:
    normalized = str(text or "")
    if not normalized.strip():
        return 0
    return max(
        count_markdown_subheadings(normalized),
        len(extract_top_level_list_items(normalized)),
    )


def detect_missing_input_response(text: str) -> tuple[bool, str]:
    normalized = str(text or "").strip()
    if not normalized:
        return False, ""

    markers = (
        "请提供以下信息",
        "请提供更多信息",
        "请提供原文",
        "请提供具体",
        "请补充",
        "请先提供",
        "需要更多信息",
        "需要补充",
        "收到您的信息后",
        "收到你提供的信息后",
        "缺少必要信息",
        "缺少原文",
        "未提供原文",
        "未提供附件",
        "请上传",
    )
    for marker in markers:
        if marker in normalized:
            return True, marker

    placeholder_patterns = (
        r"\[您提供的[^\]]*\]",
        r"\[如果知道请提供[^\]]*\]",
        r"\[数量\]",
        r"\[文件与文件夹总数\]",
        r"\[列出特别重要的文件或目录[^\]]*\]",
    )
    for pattern in placeholder_patterns:
        matched = re.search(pattern, normalized)
        if matched:
            return True, matched.group(0)

    return False, ""


WEAK_RESULT_NAME_PREFIXES = ("关注", "考虑", "选择", "优先", "建议关注", "可关注", "可能", "方向", "类型", "板块", "赛道", "主题")


def extract_top_level_list_items(text: str) -> list[str]:
    normalized = str(text or "")
    if not normalized.strip():
        return []

    items: list[str] = []
    current_parts: list[str] = []
    top_level_pattern = re.compile(r"^(?: {0,3})(?:[-*•]|\d+[\.、\)])\s+(.*\S.*)$")
    nested_pattern = re.compile(r"^(?: {4,}|\t+).+\S.*$")

    for raw_line in normalized.splitlines():
        line = raw_line.rstrip()
        top_level_match = top_level_pattern.match(line)
        if top_level_match:
            if current_parts:
                items.append("\n".join(current_parts).strip())
            current_parts = [str(top_level_match.group(1) or "").strip()]
            continue
        if current_parts and nested_pattern.match(line):
            current_parts.append(line.strip())
            continue
        if current_parts and not line.strip():
            continue
        if current_parts and line.strip() and not top_level_match:
            current_parts.append(line.strip())

    if current_parts:
        items.append("\n".join(current_parts).strip())
    return [item for item in items if item]


def normalize_result_item_label(text: str) -> str:
    first_line = str(text or "").splitlines()[0].strip()
    normalized = re.sub(r"^[*_`\-\s]+|[*_`]+$", "", first_line).strip()
    normalized = re.sub(r"^\*\*(.*?)\*\*$", r"\1", normalized).strip()
    normalized = re.sub(r"^名称[:：]\s*", "", normalized).strip()
    return normalized


def looks_like_named_result_item(text: str) -> bool:
    label = normalize_result_item_label(text)
    if len(label) < 2:
        return False
    if any(label.startswith(prefix) for prefix in WEAK_RESULT_NAME_PREFIXES):
        return False
    return True


def detect_methodology_only_research_response(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    markers = (
        "核心逻辑",
        "应用方式",
        "分析思路",
        "方法论",
        "基本原则",
        "风险提示",
        "以下几种",
        "广泛讨论",
        "可通过",
        "可以通过",
    )
    hit_count = sum(1 for marker in markers if marker in normalized)
    return hit_count >= 2


def build_pass_recovery_action(deliverable_type: str) -> dict[str, Any]:
    return {
        "version": "task-recovery-action-v1",
        "action": "none",
        "priority": "low",
        "reason": "validation_passed",
        "summary": f"{deliverable_type or 'deliverable'} 已通过校验，无需恢复动作。",
        "source": "task_runtime_validation_v1",
        "action_payload": {},
    }


def build_failed_recovery_action(
    *,
    deliverable_type: str,
    failed_checks: list[str],
    task_intent: dict[str, Any],
) -> dict[str, Any]:
    failed_set = set(failed_checks)
    action = "replan"
    priority = "medium"
    summary = "交付物未通过校验，建议重新规划后再执行。"

    if bool(task_intent.get("needs_clarification")):
        action = "clarify"
        priority = "high"
        summary = "当前任务仍存在信息缺口，建议先补充澄清再继续生成交付物。"
    elif failed_set & {"asks_for_missing_input", "contains_placeholder_template"}:
        action = "clarify"
        priority = "high"
        summary = "当前结果仍在向用户追要缺失信息，建议先澄清补全输入后再继续生成交付物。"
    elif failed_set & {
        "not_summary_only",
        "required_title_count",
        "required_body_count",
        "expected_sections",
        "primary_section_body_length",
        "research_section_body_length",
        "final_section_body_length",
        "concrete_items_count",
        "named_items_count",
        "not_methodology_only",
    }:
        action = "retry_generate"
        priority = "high"
        summary = "当前结果仍未满足最终交付要求，建议基于现有调研结果重新生成成品。"
    elif failed_set & {"non_empty", "minimum_content_length"}:
        action = "retry"
        priority = "high"
        summary = "当前结果内容不足，建议直接重试当前交付生成。"

    return {
        "version": "task-recovery-action-v1",
        "action": action,
        "priority": priority,
        "reason": "validation_failed",
        "summary": summary,
        "source": "task_runtime_validation_v1",
        "action_payload": {
            "deliverable_type": deliverable_type,
            "failed_checks": failed_checks,
        },
    }


def build_runtime_failure_recovery_action(err: str) -> dict[str, Any]:
    message = str(err or "").strip() or "runtime failure"
    return {
        "version": "task-recovery-action-v1",
        "action": "retry",
        "priority": "high",
        "reason": "runtime_failure",
        "summary": f"任务执行失败，建议优先重试或人工检查失败步骤：{message[:180]}",
        "source": "task_runtime_validation_v1",
        "action_payload": {
            "error_excerpt": message[:300],
        },
    }


def build_runtime_failure_validation_report(err: str) -> dict[str, Any]:
    message = str(err or "").strip() or "runtime failure"
    return {
        "version": "task-deliverable-validation-v1",
        "passed": False,
        "deliverable_type": "runtime_failure",
        "summary": "任务在交付物完成前已失败，尚未形成可验收成品。",
        "source": "task_runtime_validation_v1",
        "checks": [
            {
                "name": "runtime_execution_completed",
                "passed": False,
                "expected": "任务主链执行完成",
                "actual": message[:300],
            }
        ],
    }


def build_clarification_required_validation_report(
    user_input: str,
    *,
    task_intent: dict[str, Any],
    deliverable_spec: dict[str, Any],
) -> dict[str, Any]:
    reasons = [
        str(item).strip()
        for item in (task_intent.get("clarification_reasons") or [])
        if str(item).strip()
    ]
    questions = [
        str(item).strip()
        for item in (((deliverable_spec.get("clarify") or {}).get("questions")) or [])
        if str(item).strip()
    ]
    checks = [
        {
            "name": f"clarify_reason_{index}",
            "passed": False,
            "expected": "任务信息足够明确，可直接进入执行链",
            "actual": reason,
        }
        for index, reason in enumerate(reasons, start=1)
    ]
    if not checks:
        checks.append(
            {
                "name": "clarify_required",
                "passed": False,
                "expected": "任务信息足够明确，可直接进入执行链",
                "actual": "任务仍存在未明确的关键约束",
            }
        )
    return {
        "version": "task-deliverable-validation-v2",
        "passed": False,
        "deliverable_type": str(deliverable_spec.get("deliverable_type") or "clarify_required"),
        "summary": "任务存在关键输入缺口，已阻止直接执行，需先补充澄清信息。",
        "source": "task_runtime_preflight_v1",
        "task_excerpt": str(user_input or "").strip()[:160],
        "checks": checks,
        "acceptance_hints": list(deliverable_spec.get("acceptance_hints") or []),
        "clarify_questions": questions,
    }


def build_clarification_required_recovery_action(
    *,
    task_intent: dict[str, Any],
    deliverable_spec: dict[str, Any],
) -> dict[str, Any]:
    reasons = [
        str(item).strip()
        for item in (task_intent.get("clarification_reasons") or [])
        if str(item).strip()
    ]
    questions = [
        str(item).strip()
        for item in (((deliverable_spec.get("clarify") or {}).get("questions")) or [])
        if str(item).strip()
    ]
    return {
        "version": "task-recovery-action-v2",
        "action": "clarify",
        "priority": "high",
        "reason": "pre_execution_clarification_required",
        "summary": "任务在进入执行链前已识别到关键缺口，建议先通过 clarify 补充信息后再继续。",
        "source": "task_runtime_preflight_v1",
        "action_payload": {
            "clarification_reasons": reasons,
            "clarification_questions": questions,
        },
    }


def build_clarification_required_message(
    *,
    task_intent: dict[str, Any],
    deliverable_spec: dict[str, Any],
) -> str:
    reasons = [
        str(item).strip()
        for item in (task_intent.get("clarification_reasons") or [])
        if str(item).strip()
    ]
    questions = [
        str(item).strip()
        for item in (((deliverable_spec.get("clarify") or {}).get("questions")) or [])
        if str(item).strip()
    ]
    lines = ["任务需要补充澄清后再继续执行。"]
    if reasons:
        lines.append("")
        lines.append("缺少的信息：")
        lines.extend(f"- {item}" for item in reasons)
    if questions:
        lines.append("")
        lines.append("建议补充：")
        lines.extend(f"- {item}" for item in questions)
    return "\n".join(lines)


def evaluate_task_deliverable(
    *,
    task_intent: dict[str, Any],
    deliverable_spec: dict[str, Any],
    runtime_overrides: dict[str, Any],
    user_input: str,
    final_result: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    deliverable_type = str((deliverable_spec or {}).get("deliverable_type") or "direct_answer").strip() or "direct_answer"
    expected_sections = [
        str(item).strip()
        for item in ((deliverable_spec or {}).get("expected_sections") or [])
        if str(item).strip()
    ]
    quantity_hint_raw = (deliverable_spec or {}).get("quantity_hint")
    quantity_hint = int(quantity_hint_raw) if isinstance(quantity_hint_raw, int) and quantity_hint_raw > 0 else None
    requires_concrete_items = bool((deliverable_spec or {}).get("requires_concrete_items"))
    requires_named_items = bool((deliverable_spec or {}).get("requires_named_items"))
    minimum_item_count_raw = (deliverable_spec or {}).get("minimum_item_count")
    minimum_item_count = int(minimum_item_count_raw) if isinstance(minimum_item_count_raw, int) and minimum_item_count_raw > 0 else None
    concrete_section_title = str((deliverable_spec or {}).get("concrete_section_title") or "").strip()
    deliverable_text = str(final_result or "").split("\n\n产出文件：", 1)[0].strip()

    checks: list[dict[str, Any]] = []

    def append_check(name: str, passed: bool, expected: Any, actual: Any):
        checks.append(
            {
                "name": name,
                "passed": bool(passed),
                "expected": expected,
                "actual": actual,
            }
        )

    append_check("non_empty", bool(deliverable_text), "非空最终成品", f"length={len(deliverable_text)}")
    append_check(
        "not_summary_only",
        "web_search 结果" not in deliverable_text and "摘要结果：" not in deliverable_text,
        "最终结果不应只是搜索摘要/整理摘要",
        "contains_summary_markers" if ("web_search 结果" in deliverable_text or "摘要结果：" in deliverable_text) else "clean",
    )
    asks_for_missing_input, missing_input_marker = detect_missing_input_response(deliverable_text)
    append_check(
        "asks_for_missing_input",
        not asks_for_missing_input,
        "最终结果应直接交付，不应继续向用户追要缺失输入",
        missing_input_marker or "clean",
    )
    append_check(
        "contains_placeholder_template",
        "[" not in deliverable_text or not missing_input_marker.startswith("["),
        "最终结果不应保留模板占位符",
        missing_input_marker if missing_input_marker.startswith("[") else "clean",
    )

    if deliverable_type == "copywriting_bundle":
        title_count = count_markdown_heading(deliverable_text, "标题")
        body_count = count_markdown_heading(deliverable_text, "正文")
        title_item_count = count_structured_section_items(extract_first_level_section_body(deliverable_text, "标题"))
        body_item_count = count_structured_section_items(extract_first_level_section_body(deliverable_text, "正文"))
        required_count = int(quantity_hint or 1)
        append_check(
            "required_title_count",
            max(title_count, title_item_count) >= required_count,
            required_count,
            max(title_count, title_item_count),
        )
        append_check(
            "required_body_count",
            max(body_count, body_item_count) >= required_count,
            required_count,
            max(body_count, body_item_count),
        )
    elif deliverable_type == "direct_answer":
        matched_sections = sum(1 for item in expected_sections if count_markdown_heading(deliverable_text, item) > 0 or item in deliverable_text)
        append_check("expected_sections", matched_sections >= 1, ">=1", matched_sections)
        append_check("minimum_content_length", len(deliverable_text) >= 20, ">=20 chars", len(deliverable_text))
    elif deliverable_type in {"generated_content", "research_then_generate_bundle"}:
        matched_sections = sum(1 for item in expected_sections if count_markdown_heading(deliverable_text, item) > 0 or item in deliverable_text)
        expected_target = 1 if deliverable_type == "generated_content" else (len(expected_sections) or 1)
        append_check("expected_sections", matched_sections >= expected_target, expected_target, matched_sections)
        minimum_length = 60 if deliverable_type == "generated_content" else 120
        append_check("minimum_content_length", len(deliverable_text) >= minimum_length, f">={minimum_length} chars", len(deliverable_text))
        section_body_lengths = get_expected_section_body_lengths(deliverable_text, expected_sections)
        if deliverable_type == "generated_content":
            primary_section = expected_sections[0] if expected_sections else "成品内容"
            body_length = int(section_body_lengths.get(primary_section) or 0) or len(deliverable_text)
            append_check("primary_section_body_length", body_length >= 40, ">=40 chars", body_length)
        else:
            research_length = int(section_body_lengths.get("调研要点") or 0)
            final_length = int(section_body_lengths.get("最终成品") or 0)
            append_check("research_section_body_length", research_length >= 20, ">=20 chars", research_length)
            append_check("final_section_body_length", final_length >= 40, ">=40 chars", final_length)
            if requires_concrete_items:
                section_bodies = extract_markdown_section_bodies(deliverable_text)
                concrete_body = section_bodies.get(concrete_section_title or "调研要点", "")
                concrete_items = extract_top_level_list_items(concrete_body)
                concrete_items_count = len(concrete_items)
                expected_item_count = max(1, minimum_item_count or quantity_hint or 1)
                append_check("concrete_items_count", concrete_items_count >= expected_item_count, f">={expected_item_count}", concrete_items_count)
                if requires_named_items:
                    named_items_count = sum(1 for item in concrete_items if looks_like_named_result_item(item))
                    append_check("named_items_count", named_items_count >= expected_item_count, f">={expected_item_count}", named_items_count)
                methodology_only = concrete_items_count == 0 and detect_methodology_only_research_response(concrete_body or deliverable_text)
                append_check(
                    "not_methodology_only",
                    not methodology_only,
                    "调研部分应提供具体对象/候选项/案例，不应退化成方法论",
                    "methodology_only" if methodology_only else "clean",
                )
    elif deliverable_type == "rewritten_text":
        matched_sections = sum(1 for item in expected_sections if count_markdown_heading(deliverable_text, item) > 0 or item in deliverable_text)
        expected_target = len(expected_sections) or 1
        append_check("expected_sections", matched_sections >= expected_target, expected_target, matched_sections)
        append_check("minimum_content_length", len(deliverable_text) >= 40, ">=40 chars", len(deliverable_text))
    elif deliverable_type == "execution_result":
        matched_sections = sum(1 for item in expected_sections if count_markdown_heading(deliverable_text, item) > 0 or item in deliverable_text)
        expected_target = len(expected_sections) or 1
        append_check("expected_sections", matched_sections >= expected_target, expected_target, matched_sections)
        append_check("minimum_content_length", len(deliverable_text) >= 40, ">=40 chars", len(deliverable_text))
    elif deliverable_type == "research_summary":
        matched_sections = sum(1 for item in expected_sections if item in deliverable_text)
        append_check("expected_sections", matched_sections >= max(1, len(expected_sections) - 1), f">={max(1, len(expected_sections) - 1)}", matched_sections)
        append_check("minimum_content_length", len(deliverable_text) >= 80, ">=80 chars", len(deliverable_text))
        if requires_concrete_items:
            target_section = concrete_section_title or (expected_sections[1] if len(expected_sections) >= 2 else "")
            section_bodies = extract_markdown_section_bodies(deliverable_text)
            concrete_body = section_bodies.get(target_section, "") if target_section else deliverable_text
            concrete_items = extract_top_level_list_items(concrete_body)
            concrete_items_count = len(concrete_items)
            expected_item_count = max(1, minimum_item_count or quantity_hint or 1)
            append_check("concrete_items_count", concrete_items_count >= expected_item_count, f">={expected_item_count}", concrete_items_count)
            if requires_named_items:
                named_items_count = sum(1 for item in concrete_items if looks_like_named_result_item(item))
                append_check("named_items_count", named_items_count >= expected_item_count, f">={expected_item_count}", named_items_count)
            methodology_only = concrete_items_count == 0 and detect_methodology_only_research_response(deliverable_text)
            append_check(
                "not_methodology_only",
                not methodology_only,
                "结果应提供具体对象/候选项/案例，不应退化成方法论",
                "methodology_only" if methodology_only else "clean",
            )
    else:
        append_check("minimum_content_length", len(deliverable_text) >= 30, ">=30 chars", len(deliverable_text))

    passed = all(bool(item["passed"]) for item in checks)
    failed_checks = [str(item["name"]) for item in checks if not bool(item["passed"])]
    validation_report = {
        "version": "task-deliverable-validation-v1",
        "passed": passed,
        "deliverable_type": deliverable_type,
        "summary": "交付物已通过最小验收。" if passed else "交付物未通过最小验收，需要恢复动作。",
        "source": "task_runtime_validation_v1",
        "task_excerpt": build_task_display_user_input(str(user_input or ""), runtime_overrides)[:160],
        "checks": checks,
        "acceptance_hints": list((deliverable_spec or {}).get("acceptance_hints") or []),
    }
    recovery_action = (
        build_pass_recovery_action(deliverable_type)
        if passed
        else build_failed_recovery_action(
            deliverable_type=deliverable_type,
            failed_checks=failed_checks,
            task_intent=task_intent if isinstance(task_intent, dict) else {},
        )
    )
    return validation_report, recovery_action


def _json_block_for_prompt(value: dict[str, Any]) -> str:
    if not isinstance(value, dict) or not value:
        return "{}"
    return json.dumps(value, ensure_ascii=False, indent=2)


def build_deliverable_generation_prompt(
    user_input: str,
    *,
    task_intent: dict[str, Any],
    deliverable_spec: dict[str, Any],
    use_research_reference: bool,
) -> str:
    normalized_user_input = build_generation_user_input(user_input)
    expected_sections = [
        str(item).strip()
        for item in (deliverable_spec.get("expected_sections") or [])
        if str(item).strip()
    ]
    acceptance_hints = [
        str(item).strip()
        for item in (deliverable_spec.get("acceptance_hints") or [])
        if str(item).strip()
    ]
    quantity_hint = deliverable_spec.get("quantity_hint")
    requires_concrete_items = bool(deliverable_spec.get("requires_concrete_items"))
    requires_named_items = bool(deliverable_spec.get("requires_named_items"))
    concrete_section_title = str(deliverable_spec.get("concrete_section_title") or "").strip()
    prompt_parts = [
        "请根据下面任务直接产出最终成品。",
        "不要输出执行计划、不要解释你的步骤、不要只做摘要。",
        f"用户任务：{normalized_user_input}",
        f"TaskIntent：{_json_block_for_prompt(task_intent)}",
        f"DeliverableSpec：{_json_block_for_prompt(deliverable_spec)}",
    ]
    if use_research_reference:
        prompt_parts.append("参考资料如下：\n{{step.1.output}}")
    if expected_sections:
        prompt_parts.append("输出时必须使用以下一级标题：\n" + "\n".join(f"- {item}" for item in expected_sections))
    if quantity_hint:
        prompt_parts.append(f"如果任务适用，请按 {int(quantity_hint)} 个结果组织内容。")
    if requires_concrete_items:
        target_section = concrete_section_title or "具体结果"
        prompt_parts.append(f"你必须在“{target_section}”部分给出具体对象、候选项或案例；不要把结果退化成方法论总结。")
    if requires_named_items:
        prompt_parts.append("每个结果都要给出明确名称，不要只写某个方向、板块、类型或泛泛描述。")
    if acceptance_hints:
        prompt_parts.append("验收要求：\n" + "\n".join(f"- {item}" for item in acceptance_hints))
    prompt_parts.append("结果必须是可直接给用户使用的最终内容。")
    return "\n\n".join(prompt_parts)


def build_execution_result_summary_template(
    planned_steps: list[dict[str, Any]],
    *,
    user_input: str,
    task_intent: dict[str, Any],
    deliverable_spec: dict[str, Any],
) -> str:
    expected_sections = [
        str(item).strip()
        for item in (deliverable_spec.get("expected_sections") or [])
        if str(item).strip()
    ]
    acceptance_hints = [
        str(item).strip()
        for item in (deliverable_spec.get("acceptance_hints") or [])
        if str(item).strip()
    ]
    step_output_blocks: list[str] = []
    for step in planned_steps:
        step_order = int(step.get("step_order") or 0)
        if step_order <= 0:
            continue
        title = str(step.get("title") or step.get("step_name") or f"步骤 {step_order}").strip()
        tool_name = str(step.get("tool") or step.get("tool_name") or "").strip()
        step_output_blocks.append(
            f"步骤 {step_order}（{title} / {tool_name or 'unknown'}）输出：\n{{{{step.{step_order}.output}}}}"
        )

    prompt_parts = [
        "请基于下面的执行过程，整理一份可直接交付给用户的最终执行结果。",
        "不要重复输出原始逐步日志，不要只罗列步骤名称。",
        f"用户任务：{build_generation_user_input(user_input)}",
        f"TaskIntent：{_json_block_for_prompt(task_intent)}",
        f"DeliverableSpec：{_json_block_for_prompt(deliverable_spec)}",
        "执行步骤输出如下：\n" + "\n\n".join(step_output_blocks),
    ]
    if expected_sections:
        prompt_parts.append("输出时必须使用以下一级标题：\n" + "\n".join(f"- {item}" for item in expected_sections))
    if acceptance_hints:
        prompt_parts.append("验收要求：\n" + "\n".join(f"- {item}" for item in acceptance_hints))
    prompt_parts.append("请明确说明实际执行结果、关键产物、关键状态或下一步建议。")
    return "\n\n".join(prompt_parts)


def build_deliverable_validation_step(
    *,
    step_order: int,
    expected_sections: list[str],
) -> dict[str, Any]:
    validation_marker = expected_sections[0] if expected_sections else "##"
    return {
        "step_order": step_order,
        "title": "校验交付物结构",
        "tool": "if_condition",
        "input": {
            "left": f"step:{step_order - 1}.output",
            "operator": "contains",
            "right": validation_marker,
        },
        "error_strategy": "fail",
    }


def append_execution_result_closure_steps(
    planned_steps: list[dict[str, Any]],
    *,
    user_input: str,
    task_intent: dict[str, Any],
    deliverable_spec: dict[str, Any],
) -> list[dict[str, Any]]:
    if not planned_steps:
        return planned_steps

    expected_sections = [
        str(item).strip()
        for item in (deliverable_spec.get("expected_sections") or [])
        if str(item).strip()
    ]
    max_step_order = max(int(step.get("step_order") or 0) for step in planned_steps)
    summary_template = build_execution_result_summary_template(
        planned_steps,
        user_input=user_input,
        task_intent=task_intent,
        deliverable_spec=deliverable_spec,
    )
    return [
        *planned_steps,
        {
            "step_order": max_step_order + 1,
            "title": "拼装执行结果交付提示词",
            "tool": "template_render",
            "input": {
                "template": summary_template,
                "strict": True,
            },
            "error_strategy": "fail",
        },
        {
            "step_order": max_step_order + 2,
            "title": "生成执行结果成品",
            "tool": "generate_text",
            "input": {
                "prompt": f"step:{max_step_order + 1}.data.rendered_text",
                "system_prompt": "你是一个执行结果整理助手。请把执行过程整理成用户可直接使用的最终结果，明确实际执行状态与关键产物。",
            },
            "error_strategy": "fail",
        },
        build_deliverable_validation_step(
            step_order=max_step_order + 3,
            expected_sections=expected_sections or ["执行结果"],
        ),
    ]


def build_deliverable_first_plan(
    user_input: str,
    *,
    task_intent: dict[str, Any],
    deliverable_spec: dict[str, Any],
) -> list[dict[str, Any]] | None:
    deliverable_type = str(deliverable_spec.get("deliverable_type") or "").strip()
    research_query = sanitize_web_search_query(user_input)
    expected_sections = [
        str(item).strip()
        for item in (deliverable_spec.get("expected_sections") or [])
        if str(item).strip()
    ]

    if deliverable_type in {"copywriting_bundle", "research_then_generate_bundle"}:
        generation_prompt = build_deliverable_generation_prompt(
            user_input,
            task_intent=task_intent,
            deliverable_spec=deliverable_spec,
            use_research_reference=True,
        )
        return [
            {
                "step_order": 1,
                "title": "调研参考信息",
                "tool": "web_search",
                "input": {"query": research_query},
                "error_strategy": "fail",
            },
            {
                "step_order": 2,
                "title": "拼装交付提示词",
                "tool": "template_render",
                "input": {
                    "template": generation_prompt,
                    "strict": True,
                },
                "error_strategy": "fail",
            },
            {
                "step_order": 3,
                "title": "生成最终交付物",
                "tool": "generate_text",
                "input": {
                    "prompt": "step:2.data.rendered_text",
                    "system_prompt": "你是一个成品交付助手。请直接交付最终结果，结合参考资料但不要抄袭来源内容。",
                },
                "error_strategy": "fail",
            },
            build_deliverable_validation_step(step_order=4, expected_sections=expected_sections or ["标题"]),
        ]

    if deliverable_type in {"generated_content", "rewritten_text"}:
        generation_prompt = build_deliverable_generation_prompt(
            user_input,
            task_intent=task_intent,
            deliverable_spec=deliverable_spec,
            use_research_reference=False,
        )
        return [
            {
                "step_order": 1,
                "title": "生成最终交付物",
                "tool": "generate_text",
                "input": {
                    "prompt": generation_prompt,
                    "system_prompt": "你是一个成品交付助手。请直接输出最终成品，不要解释过程。",
                },
                "error_strategy": "fail",
            },
            build_deliverable_validation_step(step_order=2, expected_sections=expected_sections or ["成品内容"]),
        ]

    if deliverable_type == "research_summary":
        generation_prompt = build_deliverable_generation_prompt(
            user_input,
            task_intent=task_intent,
            deliverable_spec=deliverable_spec,
            use_research_reference=True,
        )
        return [
            {
                "step_order": 1,
                "title": "调研参考信息",
                "tool": "web_search",
                "input": {"query": research_query},
                "error_strategy": "fail",
            },
            {
                "step_order": 2,
                "title": "拼装交付提示词",
                "tool": "template_render",
                "input": {
                    "template": generation_prompt,
                    "strict": True,
                },
                "error_strategy": "fail",
            },
            {
                "step_order": 3,
                "title": "生成调研结论",
                "tool": "generate_text",
                "input": {
                    "prompt": "step:2.data.rendered_text",
                    "system_prompt": "你是一个调研交付助手。请基于参考资料输出结构化调研结论，不要只罗列原始链接。",
                },
                "error_strategy": "fail",
            },
            build_deliverable_validation_step(step_order=4, expected_sections=expected_sections or ["结论摘要"]),
        ]

    if deliverable_type == "direct_answer":
        generation_prompt = build_deliverable_generation_prompt(
            user_input,
            task_intent=task_intent,
            deliverable_spec=deliverable_spec,
            use_research_reference=False,
        )
        return [
            {
                "step_order": 1,
                "title": "生成直接答案",
                "tool": "generate_text",
                "input": {
                    "prompt": generation_prompt,
                    "system_prompt": "你是一个问答助手。请直接回答用户问题，输出最终答案，不要解释执行过程。",
                },
                "error_strategy": "fail",
            },
            build_deliverable_validation_step(step_order=2, expected_sections=expected_sections or ["答案"]),
        ]

    return None
