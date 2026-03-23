from task_intent_helpers import infer_deliverable_spec, infer_task_intent


def test_research_task_requires_clarification_when_scope_is_missing():
    intent = infer_task_intent("帮我调研一下")
    spec = infer_deliverable_spec("帮我调研一下", intent)

    assert intent["task_type"] == "research"
    assert intent["needs_clarification"] is True
    assert "调研主题不明确" in intent["clarification_reasons"]
    assert spec["clarify"]["required"] is True


def test_content_generation_extracts_deliverable_constraints():
    user_input = "帮我写一封给客户的正式道歉邮件，控制在300字内"
    intent = infer_task_intent(user_input)
    spec = infer_deliverable_spec(user_input, intent)

    assert intent["task_type"] == "content_generation"
    assert intent["needs_clarification"] is False
    assert spec["deliverable_type"] == "generated_content"
    assert spec["expected_sections"] == ["成品内容"]


def test_execution_task_is_not_misclassified_as_research():
    user_input = "修复 apps/api/main.py 里的权限问题"
    intent = infer_task_intent(user_input)
    spec = infer_deliverable_spec(user_input, intent)

    assert intent["task_type"] == "execution"
    assert intent["needs_clarification"] is False
    assert spec["deliverable_type"] == "execution_result"
    assert "执行结果" in spec["expected_sections"]
