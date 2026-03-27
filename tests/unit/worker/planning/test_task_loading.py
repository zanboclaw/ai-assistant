from apps.worker.runtime.task_loading.load_task import load_task_runtime_context


def test_load_task_runtime_context_collects_main_fields():
    payload = load_task_runtime_context(
        {
            "runtime_overrides": {"model_route_overrides": {"planner": {"provider": "demo"}}, "memory_context": {"retrieved_memories": []}},
            "task_intent_json": {"task_type": "research"},
            "deliverable_spec_json": {"deliverable_type": "report"},
        }
    )

    assert payload["task_intent"]["task_type"] == "research"
    assert payload["deliverable_spec"]["deliverable_type"] == "report"
    assert "planner" in payload["model_route_overrides"]

