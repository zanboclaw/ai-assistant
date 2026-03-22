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
CONCRETE_RESULT_REQUEST_MARKERS = ("找找", "推荐", "列出", "盘点", "收集", "名单", "清单", "候选", "哪些", "哪几个", "哪几家", "哪只", "哪几只", "给我几个", "来几个")
CONCRETE_TARGET_MARKERS = ("公司", "股票", "标的", "案例", "示例", "范例", "工具", "平台", "文案", "文章", "产品", "方案", "渠道", "对象")
ABSTRACT_RESEARCH_MARKERS = ("方法", "思路", "原理", "教程", "技巧", "步骤", "流程", "模板", "秘诀")
TIME_SENSITIVE_MARKERS = ("当前", "最近", "最新", "今天", "今日", "明天", "本周", "近期")
NAMED_RESULT_TARGET_MARKERS = ("公司", "股票", "个股", "基金", "品牌", "产品", "平台", "工具", "网站", "应用", "app", "店铺", "餐厅", "酒店", "景点", "城市", "学校", "客户", "供应商")


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


def _looks_like_concrete_results_request(text: str) -> bool:
    if _looks_like_reference_seeking_copywriting(text):
        return True
    has_request_marker = _contains_any(text, CONCRETE_RESULT_REQUEST_MARKERS)
    has_target_marker = _contains_any(text, CONCRETE_TARGET_MARKERS)
    if _contains_any(text, ABSTRACT_RESEARCH_MARKERS) and not has_target_marker:
        return False
    return bool(has_request_marker and (has_target_marker or "找" in text or "推荐" in text or "列出" in text))


def _looks_like_time_sensitive_request(text: str) -> bool:
    return _contains_any(text, TIME_SENSITIVE_MARKERS)


def _requires_named_results(text: str) -> bool:
    return _looks_like_concrete_results_request(text) and _contains_any(text, NAMED_RESULT_TARGET_MARKERS)


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
    requires_concrete_results = _looks_like_concrete_results_request(normalized)
    is_time_sensitive = _looks_like_time_sensitive_request(normalized)
    requires_named_results = _requires_named_results(normalized)

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
    if requires_concrete_results:
        matched_signals.append("concrete_results")
    if is_time_sensitive:
        matched_signals.append("time_sensitive")
    if requires_named_results:
        matched_signals.append("named_results")

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
        "requires_concrete_results": requires_concrete_results,
        "is_time_sensitive": is_time_sensitive,
        "requires_named_results": requires_named_results,
    }


def infer_deliverable_spec(user_input: str, task_intent: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_text(user_input)
    task_type = str(task_intent.get("task_type") or "qa")

    deliverable_type = "direct_answer"
    output_format = "markdown"
    expected_sections: list[str] = []
    quantity_hint: int | None = None
    acceptance_hints: list[str] = []
    requires_concrete_items = False
    requires_named_items = False
    minimum_item_count: int | None = None
    concrete_section_title = ""
    explicit_quantity = _extract_quantity_hint(normalized)
    requires_concrete_results = bool(task_intent.get("requires_concrete_results")) or _looks_like_concrete_results_request(normalized)
    is_time_sensitive = bool(task_intent.get("is_time_sensitive")) or _looks_like_time_sensitive_request(normalized)
    requires_named_results = bool(task_intent.get("requires_named_results")) or _requires_named_results(normalized)

    if _looks_like_reference_seeking_copywriting(normalized) and not _looks_like_generation_copywriting(normalized):
        deliverable_type = "research_summary"
        expected_sections = ["结论摘要", "案例要点", "来源或依据"]
        quantity_hint = explicit_quantity or 3
        requires_concrete_items = True
        minimum_item_count = quantity_hint
        concrete_section_title = "案例要点"
        acceptance_hints = [
            "输出应给出可参考文案案例或风格要点",
            f"“案例要点”部分至少给出 {int(minimum_item_count)} 个具体案例或方向",
            "每个结果都要附一句简短依据，不要退化成空泛方法论摘要",
        ]
    elif _looks_like_reference_seeking_copywriting(normalized) and _looks_like_generation_copywriting(normalized):
        deliverable_type = "research_then_generate_bundle"
        expected_sections = ["调研要点", "最终成品"]
        quantity_hint = explicit_quantity or 3
        requires_concrete_items = True
        requires_named_items = requires_named_results
        minimum_item_count = quantity_hint
        concrete_section_title = "调研要点"
        acceptance_hints = [
            "先给出可参考依据，再交付最终成品",
            "不要只返回搜索摘要",
            f"“调研要点”部分至少给出 {int(minimum_item_count)} 个具体案例、对象或方向",
        ]
        if requires_named_items:
            acceptance_hints.append("如果用户要的是公司、产品、平台、工具等实体，每个调研结果都应给出明确名称")
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
        if requires_concrete_results:
            expected_sections = ["结论摘要", "具体结果", "来源或依据"]
            quantity_hint = explicit_quantity or 3
            requires_concrete_items = True
            requires_named_items = requires_named_results
            minimum_item_count = quantity_hint
            concrete_section_title = "具体结果"
            acceptance_hints = [
                "输出应直接给出具体对象、候选项或案例，不要只讲方法论",
                f"“具体结果”部分至少给出 {int(minimum_item_count)} 个结果",
                "每个结果都要附一句简短依据或判断理由",
            ]
            if requires_named_items:
                acceptance_hints.append("每个结果都应给出明确名称，不要只写板块、方向、类型或泛泛描述")
        else:
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
        if requires_concrete_results:
            quantity_hint = explicit_quantity or 3
            requires_concrete_items = True
            requires_named_items = requires_named_results
            minimum_item_count = quantity_hint
            concrete_section_title = "调研要点"
            acceptance_hints.extend(
                [
                    f"“调研要点”部分至少给出 {int(minimum_item_count)} 个具体对象、候选项或案例",
                    "不要把调研部分退化成抽象方法论",
                ]
            )
            if requires_named_items:
                acceptance_hints.append("如果用户要的是公司、产品、平台、工具等实体，每个调研结果都应给出明确名称")
    else:
        expected_sections = ["答案"]
        acceptance_hints = ["回答应直接回应用户问题"]

    if is_time_sensitive:
        acceptance_hints.append("如果任务包含当前/近期/今天/明天等时效词，优先基于最新可得信息给出结果；若无法确认，应明确说明限制")

    return {
        "deliverable_type": deliverable_type,
        "output_format": output_format,
        "expected_sections": expected_sections,
        "quantity_hint": quantity_hint,
        "acceptance_hints": acceptance_hints,
        "requires_concrete_items": requires_concrete_items,
        "requires_named_items": requires_named_items,
        "minimum_item_count": minimum_item_count,
        "concrete_section_title": concrete_section_title,
        "source": "heuristic_v1",
    }
