from deliverable_runtime import build_deliverable_first_plan, build_execution_result_summary_template
from task_payloads import augment_user_input_with_memory_context, build_generation_user_input


def test_build_deliverable_first_plan_strips_memory_context_from_generation_prompt():
    original_user_input = "帮我找几个小红书文案"
    task_row = {
        "runtime_overrides": {
            "memory_context": {
                "retrieved_memories": [
                    {
                        "memory_kind": "conversation_memory",
                        "title": "给网站做SEO优化建议",
                        "content": "输入：给网站做SEO优化建议\n输出：以下是一份网站 SEO 优化建议清单。",
                    }
                ]
            }
        }
    }
    augmented_user_input = augment_user_input_with_memory_context(original_user_input, task_row)

    plan = build_deliverable_first_plan(
        augmented_user_input,
        task_intent={"task_type": "content_generation"},
        deliverable_spec={
            "deliverable_type": "copywriting_bundle",
            "expected_sections": ["标题", "正文"],
        },
    )

    assert plan is not None
    assert plan[1]["tool"] == "template_render"
    template = plan[1]["input"]["template"]
    assert f"用户任务：{original_user_input}" in template
    assert "可复用的长期记忆" not in template
    assert "给网站做SEO优化建议" not in template


def test_execution_result_summary_template_uses_raw_user_input():
    original_user_input = "帮我整理发布回滚要点"
    task_row = {
        "runtime_overrides": {
            "memory_context": {
                "retrieved_memories": [
                    {
                        "memory_kind": "conversation_memory",
                        "title": "旧的回滚总结",
                        "content": "上次回滚时请优先验证镜像 tag 与 migrations。",
                    }
                ]
            }
        }
    }
    augmented_user_input = augment_user_input_with_memory_context(original_user_input, task_row)

    template = build_execution_result_summary_template(
        [{"step_order": 1, "title": "收集信息", "tool": "web_search"}],
        user_input=augmented_user_input,
        task_intent={"task_type": "execution_result"},
        deliverable_spec={"deliverable_type": "execution_result"},
    )

    assert f"用户任务：{original_user_input}" in template
    assert "可复用的长期记忆" not in template
    assert build_generation_user_input(augmented_user_input) == original_user_input
