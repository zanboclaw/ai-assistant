from apps.worker.runtime.task_loading.inject_memory import inject_memory_into_user_input


def test_inject_memory_into_user_input_adds_memory_context():
    task_row = {"runtime_overrides": {"memory_context": {"retrieved_memories": [{"memory_kind": "summary", "title": "回滚", "content": "先演练回滚"}]}}}

    value = inject_memory_into_user_input("发布方案", task_row)

    assert "可复用的长期记忆" in value

