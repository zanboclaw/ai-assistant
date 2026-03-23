from __future__ import annotations

import re
from typing import Any


QUESTION_MARKERS = ("?", "？", "为什么", "如何", "怎么", "是否", "能不能", "是什么", "请问")
RESEARCH_MARKERS = ("调研", "研究", "搜集", "搜索", "查找", "找找", "对比", "分析", "整理资料", "总结资料", "参考", "案例", "示例", "范例", "盘点", "收集")
CONTENT_MARKERS = ("写", "生成", "输出", "整理一份", "写一版", "文案", "邮件", "方案", "报告", "介绍", "脚本", "文章")
REWRITE_MARKERS = ("改写", "润色", "优化文案", "重写", "改成", "换个说法", "压缩一下", "扩写", "精简")
EXECUTION_MARKERS = ("执行", "运行", "调用", "创建文件", "修改文件", "部署", "提交", "发布", "修复", "实现", "改一下", "接入")
COPYWRITING_REFERENCE_MARKERS = ("参考", "案例", "示例", "范例", "合集", "盘点", "灵感", "当前不错", "最近不错", "收集", "找找", "看看")
COPYWRITING_GENERATION_MARKERS = ("帮我写", "给我写", "写几条", "生成", "输出", "起草", "创作", "仿写")
CONCRETE_RESULT_REQUEST_MARKERS = ("找找", "推荐", "列出", "盘点", "收集", "名单", "清单", "候选", "哪些", "哪几个", "哪几家", "哪只", "哪几只", "给我几个", "来几个")
CONCRETE_TARGET_MARKERS = ("公司", "股票", "标的", "案例", "示例", "范例", "工具", "平台", "文案", "文章", "产品", "方案", "渠道", "对象")
ABSTRACT_RESEARCH_MARKERS = ("方法", "思路", "原理", "教程", "技巧", "步骤", "流程", "模板", "秘诀")
TIME_SENSITIVE_MARKERS = ("当前", "最近", "最新", "今天", "今日", "明天", "本周", "近期")
NAMED_RESULT_TARGET_MARKERS = ("公司", "股票", "个股", "基金", "品牌", "产品", "平台", "工具", "网站", "应用", "app", "店铺", "餐厅", "酒店", "景点", "城市", "学校", "客户", "供应商")
AUDIENCE_MARKERS = ("面向", "给", "用于", "读者", "用户", "客户", "老板", "学生", "家长", "面试官", "候选人")
STYLE_MARKERS = ("风格", "语气", "口吻", "正式", "口语", "专业", "简洁", "幽默", "严肃", "小红书", "朋友圈", "邮件体")
FORMAT_MARKERS = ("表格", "markdown", "分点", "一级标题", "json", "邮件", "报告", "清单", "方案", "ppt", "大纲", "脚本")
EXECUTION_TARGET_MARKERS = ("文件", "目录", "接口", "服务", "数据库", "表", "脚本", "页面", "组件", "函数", "类", "模块", "docker", "redis", "postgres", "api", "worker")
REFERENCE_SOURCE_MARKERS = ("原文", "以下内容", "这段话", "下面这段", "帮我改写", "请润色", "根据下面")
GENERIC_VAGUE_MARKERS = ("这个", "那个", "一下", "随便", "看看", "帮我弄", "帮我搞", "帮我处理")

TASK_INTENT_TEMPLATES: dict[str, dict[str, Any]] = {
    "qa": {
        "label": "问答",
        "interaction_mode": "execute",
        "deliverable_type": "direct_answer",
        "expected_sections": ["答案", "关键依据"],
        "acceptance_hints": [
            "先直接回答问题，再补充必要依据",
            "不要输出执行计划或无关步骤说明",
        ],
        "clarify_questions": [
            "你希望我回答的具体问题或主题是什么？",
            "结果更偏结论回答、对比分析，还是候选清单？",
        ],
    },
    "research": {
        "label": "调研",
        "interaction_mode": "execute",
        "deliverable_type": "research_summary",
        "expected_sections": ["结论摘要", "具体结果", "来源或依据"],
        "acceptance_hints": [
            "调研结果应包含可直接使用的结论或候选项",
            "不要只返回搜索摘要或原始链接堆砌",
        ],
        "clarify_questions": [
            "具体要调研什么主题、对象或范围？",
            "你要的是结论摘要、候选清单，还是调研后产出成品？",
            "数量、地区、时间范围是否有限定？",
        ],
    },
    "content_generation": {
        "label": "内容生成",
        "interaction_mode": "execute",
        "deliverable_type": "generated_content",
        "expected_sections": ["成品内容"],
        "acceptance_hints": [
            "直接交付可用成品，不要只给写作思路",
            "内容应符合用户指定的格式、对象和语气",
        ],
        "clarify_questions": [
            "内容面向谁、用在什么场景？",
            "希望什么风格、格式或结构？",
            "数量、字数或版本数有没有要求？",
        ],
    },
    "rewrite": {
        "label": "改写",
        "interaction_mode": "execute",
        "deliverable_type": "rewritten_text",
        "expected_sections": ["改写结果"],
        "acceptance_hints": [
            "输出应直接给出改写后的成品文本",
            "不要只点评原文问题而不产生成品",
        ],
        "clarify_questions": [
            "请提供需要改写或润色的原文内容。",
            "希望改成什么风格、语气或长度？",
        ],
    },
    "execution": {
        "label": "执行",
        "interaction_mode": "execute",
        "deliverable_type": "execution_result",
        "expected_sections": ["执行结果", "关键产物或状态", "下一步建议"],
        "acceptance_hints": [
            "说明实际执行结果，而不是只给计划",
            "需要明确关键产物、状态变化或阻塞点",
        ],
        "clarify_questions": [
            "要执行的具体对象是什么，例如文件、模块、接口、服务或环境？",
            "你期待的完成状态或验收结果是什么？",
        ],
    },
    "mixed": {
        "label": "调研后交付",
        "interaction_mode": "execute",
        "deliverable_type": "research_then_generate_bundle",
        "expected_sections": ["调研要点", "最终成品", "验收自检"],
        "acceptance_hints": [
            "必须同时给出依据和最终成品",
            "不要停在调研摘要或思路说明",
        ],
        "clarify_questions": [
            "需要先调研什么，再交付什么最终成品？",
            "最终成品的格式、对象和数量要求是什么？",
        ],
    },
}


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
    match = re.search(r"(\d+)\s*(条|个|篇|版|组|份|家|只|段)", text)
    if match:
        value = int(match.group(1))
        if value > 0:
            return value
    if "几个" in text or "多条" in text or "多版" in text:
        return 3
    return None


def _has_format_constraint(text: str) -> bool:
    return _contains_any(text, FORMAT_MARKERS)


def _has_audience_constraint(text: str) -> bool:
    return _contains_any(text, AUDIENCE_MARKERS)


def _has_style_constraint(text: str) -> bool:
    return _contains_any(text, STYLE_MARKERS)


def _has_execution_target(text: str) -> bool:
    if _contains_any(text, EXECUTION_TARGET_MARKERS):
        return True
    return bool(re.search(r"(/[a-z0-9._-]+)+", text) or re.search(r"[a-z0-9_.-]+\.(py|ts|tsx|js|json|md|yaml|yml|sh|sql|html|css)", text))


def _has_reference_source(text: str) -> bool:
    if _contains_any(text, REFERENCE_SOURCE_MARKERS):
        return True
    if "```" in text:
        return True
    if re.search(r"[“\"']{1}.+[”\"']{1}", text):
        return True
    return bool(re.search(r"[:：]\s*.+", text) and len(text) >= 20)


def _looks_like_topic_specific(text: str) -> bool:
    if len(text) >= 14 and not _contains_any(text, GENERIC_VAGUE_MARKERS):
        return True
    return bool(re.search(r"(关于|围绕|针对|面向|用于|给|在)\S+", text))


def _select_task_type(
    *,
    skill_id: str | None,
    is_question: bool,
    is_research: bool,
    is_rewrite: bool,
    is_execution: bool,
    is_content: bool,
) -> str:
    if is_rewrite:
        return "rewrite"
    if skill_id and is_execution:
        return "execution"
    if is_execution and (is_research or is_content):
        return "mixed"
    if is_execution:
        return "execution"
    if is_research and is_content:
        return "mixed"
    if is_content:
        return "content_generation"
    if is_research:
        return "research"
    if is_question:
        return "qa"
    return "qa"


def _build_clarification_payload(
    *,
    normalized: str,
    task_type: str,
    quantity_hint: int | None,
    skill_id: str | None,
) -> tuple[bool, list[str], list[str], list[str]]:
    reasons: list[str] = []
    questions: list[str] = []
    focus: list[str] = []

    def add_reason(reason: str, question: str, item_focus: str):
        if reason not in reasons:
            reasons.append(reason)
        if question and question not in questions:
            questions.append(question)
        if item_focus and item_focus not in focus:
            focus.append(item_focus)

    if len(normalized) < 8:
        add_reason("输入过短，缺少足够上下文", "请补充更具体的任务目标、对象和期望结果。", "goal")

    if task_type == "qa":
        if len(normalized) < 14 and not _looks_like_topic_specific(normalized):
            add_reason("问题主题不够具体", "请明确你希望回答的具体主题或问题范围。", "topic")

    if task_type == "research":
        if not _looks_like_topic_specific(normalized):
            add_reason("调研主题不明确", "请明确要调研的对象、行业、产品或问题范围。", "topic")
        if quantity_hint is None and not _looks_like_concrete_results_request(normalized):
            add_reason("调研结果范围不明确", "请说明你希望输出候选清单、结论摘要还是方案建议，以及数量或范围。", "scope")

    if task_type == "content_generation":
        if not (_has_audience_constraint(normalized) or _has_style_constraint(normalized) or _has_format_constraint(normalized)):
            add_reason("成品约束不足，缺少对象/风格/格式要求", "请说明内容面向谁、使用场景是什么，以及希望的风格或格式。", "content_constraints")
        if quantity_hint is None and "一份" not in normalized and "一版" not in normalized and "一封" not in normalized:
            add_reason("内容数量不明确", "请说明需要几条、几版、多少字，或至少说明只要一份成品。", "quantity")

    if task_type == "rewrite":
        if not _has_reference_source(normalized):
            add_reason("缺少待改写原文", "请提供需要改写、润色或重写的原文内容。", "source_text")
        if not (_has_style_constraint(normalized) or quantity_hint is not None or _has_format_constraint(normalized)):
            add_reason("改写目标不明确", "请说明希望改成什么风格、长度、语气或结构。", "rewrite_constraints")

    if task_type == "execution":
        if not skill_id and not _has_execution_target(normalized):
            add_reason("执行对象不明确", "请明确要操作的文件、模块、接口、服务或环境。", "execution_target")
        if not re.search(r"(修复|实现|创建|修改|删除|部署|接入|补充|新增|重构|运行|执行)", normalized):
            add_reason("执行动作不够清晰", "请明确要执行的动作和预期完成状态。", "execution_action")

    if task_type == "mixed":
        if not _looks_like_topic_specific(normalized):
            add_reason("调研与成品目标都不够明确", "请分别说明需要调研什么，以及最终要交付什么成品。", "topic")
        if not (_has_format_constraint(normalized) or _has_audience_constraint(normalized) or _has_style_constraint(normalized)):
            add_reason("最终成品约束不足", "请说明最终成品的格式、对象、风格或使用场景。", "content_constraints")

    needs_clarification = bool(reasons)
    template_questions = list((TASK_INTENT_TEMPLATES.get(task_type) or {}).get("clarify_questions") or [])
    for item in template_questions:
        if len(questions) >= 3:
            break
        if item not in questions:
            questions.append(item)

    return needs_clarification, reasons, questions[:3], focus


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
    quantity_hint = _extract_quantity_hint(normalized)

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
    if quantity_hint:
        matched_signals.append("quantity_hint")

    task_type = _select_task_type(
        skill_id=skill_id,
        is_question=is_question,
        is_research=is_research,
        is_rewrite=is_rewrite,
        is_execution=is_execution,
        is_content=is_content,
    )
    template = TASK_INTENT_TEMPLATES.get(task_type, TASK_INTENT_TEMPLATES["qa"])
    needs_clarification, clarification_reasons, clarification_questions, clarify_focus = _build_clarification_payload(
        normalized=normalized,
        task_type=task_type,
        quantity_hint=quantity_hint,
        skill_id=skill_id,
    )

    confidence = 0.6
    if task_type in {"rewrite", "execution"}:
        confidence = 0.88
    elif task_type in {"research", "content_generation"}:
        confidence = 0.8
    elif task_type == "mixed":
        confidence = 0.72
    if needs_clarification:
        confidence = max(0.45, confidence - 0.18)

    return {
        "task_type": task_type,
        "task_template": task_type,
        "task_template_label": template["label"],
        "goal_summary": user_input.strip()[:160],
        "interaction_mode": "clarify_then_execute" if needs_clarification else template["interaction_mode"],
        "source": "heuristic_v2",
        "confidence": confidence,
        "needs_clarification": needs_clarification,
        "clarification_reasons": clarification_reasons,
        "clarification_questions": clarification_questions,
        "clarify_focus": clarify_focus,
        "matched_signals": matched_signals,
        "requires_concrete_results": requires_concrete_results,
        "is_time_sensitive": is_time_sensitive,
        "requires_named_results": requires_named_results,
        "quantity_hint": quantity_hint,
        "routing_hint": "task",
    }


def infer_deliverable_spec(user_input: str, task_intent: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_text(user_input)
    task_type = str(task_intent.get("task_type") or "qa")
    template = TASK_INTENT_TEMPLATES.get(task_type, TASK_INTENT_TEMPLATES["qa"])

    deliverable_type = str(template.get("deliverable_type") or "direct_answer")
    output_format = "markdown"
    expected_sections = list(template.get("expected_sections") or [])
    quantity_hint = _extract_quantity_hint(normalized) or task_intent.get("quantity_hint")
    acceptance_hints = list(template.get("acceptance_hints") or [])
    requires_concrete_items = False
    requires_named_items = False
    minimum_item_count: int | None = None
    concrete_section_title = ""

    requires_concrete_results = bool(task_intent.get("requires_concrete_results")) or _looks_like_concrete_results_request(normalized)
    is_time_sensitive = bool(task_intent.get("is_time_sensitive")) or _looks_like_time_sensitive_request(normalized)
    requires_named_results = bool(task_intent.get("requires_named_results")) or _requires_named_results(normalized)
    needs_clarification = bool(task_intent.get("needs_clarification"))
    clarification_reasons = [str(item).strip() for item in (task_intent.get("clarification_reasons") or []) if str(item).strip()]
    clarification_questions = [str(item).strip() for item in (task_intent.get("clarification_questions") or []) if str(item).strip()]

    if _looks_like_reference_seeking_copywriting(normalized) and not _looks_like_generation_copywriting(normalized):
        deliverable_type = "research_summary"
        expected_sections = ["结论摘要", "案例要点", "来源或依据"]
        quantity_hint = quantity_hint or 3
        requires_concrete_items = True
        minimum_item_count = int(quantity_hint)
        concrete_section_title = "案例要点"
        acceptance_hints.extend(
            [
                "输出应给出可参考文案案例或风格要点",
                f"“案例要点”部分至少给出 {int(minimum_item_count)} 个具体案例或方向",
                "每个结果都要附一句简短依据，不要退化成空泛方法论摘要",
            ]
        )
    elif _looks_like_reference_seeking_copywriting(normalized) and _looks_like_generation_copywriting(normalized):
        deliverable_type = "research_then_generate_bundle"
        expected_sections = ["调研要点", "最终成品", "验收自检"]
        quantity_hint = quantity_hint or 3
        requires_concrete_items = True
        requires_named_items = requires_named_results
        minimum_item_count = int(quantity_hint)
        concrete_section_title = "调研要点"
        acceptance_hints.extend(
            [
                "先给出参考依据，再交付最终成品",
                "不要只返回搜索摘要",
                f"“调研要点”部分至少给出 {int(minimum_item_count)} 个具体案例、对象或方向",
            ]
        )
    elif "小红书" in normalized and "文案" in normalized:
        deliverable_type = "copywriting_bundle"
        expected_sections = ["标题", "正文"]
        quantity_hint = quantity_hint or 3
        acceptance_hints.extend(["每条文案应可直接使用", "不要只返回搜索摘要"])
    elif task_type == "rewrite":
        deliverable_type = "rewritten_text"
        expected_sections = ["改写结果"]
        acceptance_hints.append("输出应直接给出改写成品")
    elif task_type == "research":
        deliverable_type = "research_summary"
        if requires_concrete_results:
            expected_sections = ["结论摘要", "具体结果", "来源或依据"]
            quantity_hint = quantity_hint or 3
            requires_concrete_items = True
            requires_named_items = requires_named_results
            minimum_item_count = int(quantity_hint)
            concrete_section_title = "具体结果"
            acceptance_hints.extend(
                [
                    "输出应直接给出具体对象、候选项或案例，不要只讲方法论",
                    f"“具体结果”部分至少给出 {int(minimum_item_count)} 个结果",
                    "每个结果都要附一句简短依据或判断理由",
                ]
            )
        else:
            expected_sections = ["结论摘要", "关键要点", "来源或依据"]
            acceptance_hints.append("输出应是调研结果，不只是原始链接")
    elif task_type == "content_generation":
        deliverable_type = "generated_content"
        expected_sections = ["成品内容"]
        acceptance_hints.append("输出应是成品，而不是执行计划")
    elif task_type == "execution":
        deliverable_type = "execution_result"
        expected_sections = ["执行结果", "关键产物或状态", "下一步建议"]
        acceptance_hints.extend(["需要说明实际执行结果", "不要只返回原始日志或步骤列表"])
    elif task_type == "mixed":
        deliverable_type = "research_then_generate_bundle"
        expected_sections = ["调研要点", "最终成品", "验收自检"]
        acceptance_hints.append("既要有依据，也要有最终交付物")
        if requires_concrete_results:
            quantity_hint = quantity_hint or 3
            requires_concrete_items = True
            requires_named_items = requires_named_results
            minimum_item_count = int(quantity_hint)
            concrete_section_title = "调研要点"
            acceptance_hints.extend(
                [
                    f"“调研要点”部分至少给出 {int(minimum_item_count)} 个具体对象、候选项或案例",
                    "不要把调研部分退化成抽象方法论",
                ]
            )
    else:
        deliverable_type = "direct_answer"
        expected_sections = ["答案", "关键依据"]
        acceptance_hints.append("回答应直接回应用户问题")

    if requires_named_items:
        acceptance_hints.append("每个结果都应给出明确名称，不要只写方向、类型或抽象描述")
    if is_time_sensitive:
        acceptance_hints.append("如果任务包含当前/近期/今天/明天等时效词，应优先基于最新可得信息给出结果；若无法确认，应明确说明限制")
    if needs_clarification:
        acceptance_hints.append("当前任务仍有信息缺口，未补充澄清前不要假设关键约束。")

    return {
        "deliverable_type": deliverable_type,
        "output_format": output_format,
        "expected_sections": expected_sections,
        "quantity_hint": int(quantity_hint) if isinstance(quantity_hint, int) and quantity_hint > 0 else None,
        "acceptance_hints": acceptance_hints,
        "requires_concrete_items": requires_concrete_items,
        "requires_named_items": requires_named_items,
        "minimum_item_count": minimum_item_count,
        "concrete_section_title": concrete_section_title,
        "clarify": {
            "required": needs_clarification,
            "blocking": needs_clarification,
            "reasons": clarification_reasons,
            "questions": clarification_questions,
        },
        "source": "heuristic_v2",
    }
