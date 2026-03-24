from deliverable_runtime import evaluate_task_deliverable
from worker import (
    build_clarification_required_recovery_action,
    build_clarification_required_validation_report,
    build_failed_recovery_action,
)


def test_clarification_preflight_builds_blocking_recovery_action():
    task_intent = {
        "needs_clarification": True,
        "clarification_reasons": ["调研主题不明确"],
    }
    deliverable_spec = {
        "deliverable_type": "research_summary",
        "clarify": {
            "questions": ["请明确要调研的对象、行业、产品或问题范围。"],
        },
        "acceptance_hints": ["输出应包含可直接使用的结论。"],
    }

    report = build_clarification_required_validation_report(
        "帮我调研一下",
        task_intent=task_intent,
        deliverable_spec=deliverable_spec,
    )
    action = build_clarification_required_recovery_action(
        task_intent=task_intent,
        deliverable_spec=deliverable_spec,
    )

    assert report["passed"] is False
    assert action["action"] == "clarify"
    assert action["action_payload"]["clarification_reasons"] == ["调研主题不明确"]


def test_failed_recovery_action_prefers_retry_generate_for_incomplete_deliverable():
    action = build_failed_recovery_action(
        deliverable_type="research_summary",
        failed_checks=["expected_sections", "not_methodology_only"],
        task_intent={"needs_clarification": False},
    )

    assert action["action"] == "retry_generate"


def test_copywriting_bundle_validation_accepts_grouped_title_and_body_sections():
    final_result = """# 标题

## 1.
第一条标题

## 2.
第二条标题

## 3.
第三条标题

# 正文

## 1.
第一条正文

## 2.
第二条正文

## 3.
第三条正文
"""

    report, recovery_action = evaluate_task_deliverable(
        task_intent={"needs_clarification": False},
        deliverable_spec={
            "deliverable_type": "copywriting_bundle",
            "quantity_hint": 3,
            "expected_sections": ["标题", "正文"],
            "acceptance_hints": ["每条文案应可直接使用"],
        },
        runtime_overrides={},
        user_input="帮我找几个小红书文案",
        final_result=final_result,
    )

    assert report["passed"] is True
    assert recovery_action["action"] == "none"
