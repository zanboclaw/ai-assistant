from apps.worker.runtime.delivery.validate_deliverable import fetch_task_validation_context, validate_task_deliverable


class FakeCursor:
    def __init__(self, row):
        self.row = row
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((" ".join(str(sql).split()), params))

    def fetchone(self):
        return self.row


def test_fetch_task_validation_context_normalizes_payloads():
    cur = FakeCursor(
        {
            "task_intent_json": {"task_type": "research"},
            "deliverable_spec_json": {"deliverable_type": "research_summary"},
            "runtime_overrides": {"memory_context": {"retrieved_memories": []}},
        }
    )

    payload = fetch_task_validation_context(
        cur,
        7,
        parse_jsonish=lambda value, _default: value,
        normalize_runtime_overrides=lambda value: value,
    )

    assert payload["task_intent"]["task_type"] == "research"
    assert payload["deliverable_spec"]["deliverable_type"] == "research_summary"


def test_validate_task_deliverable_uses_loaded_context():
    calls = []

    result = validate_task_deliverable(
        object(),
        9,
        user_input="整理发布方案",
        final_result="最终交付",
        fetch_task_validation_context_fn=lambda _cur, task_id: {
            "task_intent": {"task_type": "research", "task_id": task_id},
            "deliverable_spec": {"deliverable_type": "research_summary"},
            "runtime_overrides": {"memory_context": {}},
        },
        evaluate_task_deliverable_fn=lambda **kwargs: (
            calls.append(kwargs),
            ({"passed": True, "deliverable_type": kwargs["deliverable_spec"]["deliverable_type"]}, {"action": "none"}),
        )[1],
    )

    assert result[0]["passed"] is True
    assert calls[0]["task_intent"]["task_id"] == 9
    assert calls[0]["final_result"] == "最终交付"
