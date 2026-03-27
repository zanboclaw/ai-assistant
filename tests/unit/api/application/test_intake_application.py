from apps.api.application.intake.analyze_input import analyze_input


def test_analyze_input_builds_preview(monkeypatch):
    monkeypatch.setattr("apps.api.application.intake.analyze_input.infer_task_intent", lambda user_input, skill_id=None: {"task_type": "qa"})
    monkeypatch.setattr("apps.api.application.intake.analyze_input.infer_deliverable_spec", lambda user_input, task_intent: {"deliverable_type": "direct_answer"})
    monkeypatch.setattr("apps.api.application.intake.analyze_input.build_memory_context", lambda cur, user_input: {"retrieved_memories": [], "retrieval_query": user_input})

    payload = analyze_input(None, "帮我整理回滚 checklist")

    assert payload["route_mode"] == "fast_path"
    assert payload["draft_preview"]["deliverable_type"] == "direct_answer"

