from apps.worker.runtime.planning.build_execution_plan import build_execution_plan
from apps.worker.runtime.planning.build_intent_plan import build_intent_plan


def test_build_intent_plan_merges_deliverable_and_memory_signals():
    payload = build_intent_plan(
        {
            "user_input": "整理发布方案",
            "task_intent": {"task_type": "research", "goal_summary": "整理发布方案"},
            "deliverable_spec": {"deliverable_type": "research_summary", "clarify": {"blocking": False}},
            "skill_invocation": {"skill_id": "demo_skill"},
            "memory_context": {"retrieved_memories": [{"id": 1}, {"id": 2}]},
        }
    )

    assert payload["task_type"] == "research"
    assert payload["deliverable_type"] == "research_summary"
    assert payload["skill_id"] == "demo_skill"
    assert payload["memory_hits"] == 2


def test_build_execution_plan_delegates_to_selector_with_runtime_context():
    calls = []

    result = build_execution_plan(
        object(),
        task_id=17,
        planner_user_input="整理发布方案",
        task_context={
            "skill_invocation": {"skill_id": "demo_skill"},
            "deliverable_spec": {"deliverable_type": "research_summary"},
            "model_route_overrides": {"planner": {"provider": "demo"}},
        },
        intent_plan={"task_type": "research"},
        select_task_plan_source=lambda cur, task_id, planner_user_input, **kwargs: (
            calls.append((cur, task_id, planner_user_input, kwargs)),
            {"plan_source": "planner_v2", "steps": [{"step_order": 1}]},
        )[1],
    )

    assert result["plan_source"] == "planner_v2"
    assert calls[0][1] == 17
    assert calls[0][3]["skill_invocation"]["skill_id"] == "demo_skill"
    assert calls[0][3]["model_route_overrides"]["planner"]["provider"] == "demo"
