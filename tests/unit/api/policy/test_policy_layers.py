from apps.api.domain.task.policies import task_requires_human_attention


def test_task_attention_policy_flags_recoverable_states():
    assert task_requires_human_attention({"status": "waiting_clarification"}) is True
    assert task_requires_human_attention({"status": "completed"}) is False

