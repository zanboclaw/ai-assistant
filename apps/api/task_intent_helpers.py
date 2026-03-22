from __future__ import annotations

import re
from typing import Any


QUESTION_MARKERS = ("?", "？", "为什么", "如何", "怎么", "是否", "能不能", "是什么")
RESEARCH_MARKERS = ("调研", "研究", "搜集", "搜索", "查找", "找找", "对比", "分析", "整理资料", "总结资料", "参考", "案例", "示例", "范例", "盘点", "收集")
CONTENT_MARKERS = ("写", "生成", "输出", "整理一份", "写一版", "文案", "邮件", "方案", "报告", "介绍")
REWRITE_MARKERS = ("改写", "润色", "优化文案", "重写", "改成", "换个说法", "压缩一下", "扩写")
EXECUTION_MARKERS = ("执行", "运行", "调用", "创建文件", "修改文件", "部署", "提交", "发布", "修复")
COPYWRITING_REFERENCE_MARKERS = ("参考", "案例", "示例", "范例", "合集", "盘点", "灵感", "当前不错", "最近不错", "收集", "找找", "看看")
COPYWRITING_GENERATION_MARKERS = ("帮我写", "给我写", "写几条", "生成", "输出", "起草", "创作", "仿写")


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _looks_like_reference_seeking_copywriting(text: str) -> bool:
    return "小红书" in text and "文案" in text and (
        _contains_any(text, COPYWRITING_REFERENCE_MARKERS) or _contains_any(text, RESEARCH_MARKERS)
    )


def _looks_like_generation_copywriting(text: str) -> bool:
    return "小红书" in text and "文案" in text and _contains_any(text, COPYWRITING_GENERATION_MARKERS)


def _extract_quantity_hint(text: str) -> int | None:
    match = re.search(r"(\d+)\s*(条|个|篇|版|组|份)", text)
    if match:
        value = int(match.group(1))
        if value > 0:
            return value
    return None


def infer_task_intent(user_input: str, *, skill_id: str | None = None) -> dict[str, Any]:
    normalized = _normalize_text(user_input)
    matched_signals: list[str] = []

    is_question = _contains_any(normalized, QUESTION_MARKERS)
    is_research = _contains_any(normalized, RESEARCH_MARKERS)
    is_rewrite = _contains_any(normalized, REWRITE_MARKERS)
    is_execution = _contains_any(normalized, EXECUTION_MARKERS)
    is_content = _contains_any(normalized, CONTENT_MARKERS)

    if skill_id:
        matched_signals.append("explicit_skill")
    if is_question:
        matched_signals.append("question")
    if is_research:
        matched_signals.append("research")
    if is_rewrite:
        matched_signals.append("rewrite")
    if is_execution:
        matched_signals.append("execution")
    if is_content:
        matched_signals.append("content")

    task_type = "qa"
    if is_rewrite:
        task_type = "rewrite"
    elif is_execution and (is_research or is_content):
        task_type = "mixed"
    elif is_execution:
        task_type = "execution"
    elif is_research and is_content:
        task_type = "mixed"
    elif is_content:
        task_type = "content_generation"
    elif is_research:
        task_type = "research"
    elif is_question:
        task_type = "qa"

    confidence = 0.55
    if task_type in {"rewrite", "execution"}:
        confidence = 0.84
    elif task_type in {"research", "content_generation"}:
        confidence = 0.76
    elif task_type == "mixed":
        confidence = 0.68

    needs_clarification = False
    if len(normalized) < 8:
        needs_clarification = True
    if task_type in {"mixed", "content_generation"} and not re.search(r"\d", normalized) and "几个" not in normalized and "一份" not in normalized:
        needs_clarification = True

    return {
        "task_type": task_type,
        "goal_summary": user_input.strip()[:160],
        "interaction_mode": "execute",
        "source": "heuristic_v1",
        "confidence": confidence,
        "needs_clarification": needs_clarification,
        "matched_signals": matched_signals,
    }


def infer_deliverable_spec(user_input: str, task_intent: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_text(user_input)
    task_type = str(task_intent.get("task_type") or "qa")

    deliverable_type = "direct_answer"
    output_format = "markdown"
    expected_sections: list[str] = []
    quantity_hint: int | None = None
    acceptance_hints: list[str] = []
    explicit_quantity = _extract_quantity_hint(normalized)

    if _looks_like_reference_seeking_copywriting(normalized) and not _looks_like_generation_copywriting(normalized):
        deliverable_type = "research_summary"
        expected_sections = ["结论摘要", "案例要点", "来源或依据"]
        acceptance_hints = ["输出应给出可参考文案案例或风格要点", "不要退化成空泛方法论摘要"]
    elif _looks_like_reference_seeking_copywriting(normalized) and _looks_like_generation_copywriting(normalized):
        deliverable_type = "research_then_generate_bundle"
        expected_sections = ["调研要点", "最终成品"]
        quantity_hint = explicit_quantity or 3
        acceptance_hints = ["先给出可参考依据，再交付最终成品", "不要只返回搜索摘要"]
    elif "小红书" in normalized and "文案" in normalized:
        deliverable_type = "copywriting_bundle"
        expected_sections = ["标题", "正文"]
        quantity_hint = explicit_quantity or (5 if ("几个" in normalized or "多条" in normalized) else 3)
        acceptance_hints = ["每条文案应可直接使用", "不要只返回搜索摘要"]
    elif task_type == "rewrite":
        deliverable_type = "rewritten_text"
        expected_sections = ["改写结果"]
        acceptance_hints = ["输出应直接给出改写成品"]
    elif task_type == "research":
        deliverable_type = "research_summary"
        expected_sections = ["结论摘要", "要点", "来源或依据"]
        acceptance_hints = ["输出应是调研结果，不只是原始链接"]
    elif task_type == "content_generation":
        deliverable_type = "generated_content"
        expected_sections = ["成品内容"]
        acceptance_hints = ["输出应是成品，而不是执行计划"]
    elif task_type == "execution":
        deliverable_type = "execution_result"
        expected_sections = ["执行结果", "关键产物或状态"]
        acceptance_hints = ["需要说明实际执行结果", "不要只返回原始日志或步骤列表"]
    elif task_type == "mixed":
        deliverable_type = "research_then_generate_bundle"
        expected_sections = ["调研要点", "最终成品"]
        acceptance_hints = ["既要有依据，也要有最终交付物"]
    else:
        expected_sections = ["答案"]
        acceptance_hints = ["回答应直接回应用户问题"]

    return {
        "deliverable_type": deliverable_type,
        "output_format": output_format,
        "expected_sections": expected_sections,
        "quantity_hint": quantity_hint,
        "acceptance_hints": acceptance_hints,
        "source": "heuristic_v1",
    }
