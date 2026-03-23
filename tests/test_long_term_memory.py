from core.long_term_memory import (
    build_long_term_memory_key,
    normalize_memory_keywords,
    serialize_long_term_memory_row,
)
from worker import resolve_specialist_fanout_strategy


def test_normalize_memory_keywords_dedupes_tokens():
    keywords = normalize_memory_keywords("Ubuntu 自建 AI 助手", "Ubuntu DevOps 助手")

    assert "ubuntu" in keywords
    assert "助手" in keywords
    assert len(keywords) == len(set(keywords))


def test_long_term_memory_key_is_stable():
    key_one = build_long_term_memory_key("task_memory", "方案总结", "这里是一段总结")
    key_two = build_long_term_memory_key("task_memory", "方案总结", "这里是一段总结")

    assert key_one == key_two


def test_serialize_long_term_memory_row_parses_json_fields():
    row = {
        "id": 7,
        "memory_key": "abc",
        "memory_kind": "pattern_memory",
        "source_session_id": 2,
        "source_task_id": 9,
        "actor_name": "local_operator",
        "title": "偏好",
        "content": "以后请分点回答",
        "keywords_json": '["以后","分点"]',
        "metadata_json": '{"category":"preference"}',
        "hit_count": 3,
    }

    serialized = serialize_long_term_memory_row(row)

    assert serialized["keywords"] == ["以后", "分点"]
    assert serialized["metadata"]["category"] == "preference"


def test_specialist_fanout_strategy_prefers_breadth_for_research_tasks():
    strategy = resolve_specialist_fanout_strategy(
        {
            "task_intent_json": {"task_type": "research", "needs_clarification": False},
            "deliverable_spec_json": {"deliverable_type": "research_summary"},
        },
        latest_evaluator={},
    )

    assert strategy["enabled"] is True
    assert strategy["specialist_count"] >= 2


def test_specialist_fanout_strategy_uses_feedback_for_retry():
    strategy = resolve_specialist_fanout_strategy(
        {
            "task_intent_json": {"task_type": "question_answer", "needs_clarification": False},
            "deliverable_spec_json": {"deliverable_type": "direct_answer"},
        },
        latest_evaluator={
            "decision": "rework_required",
            "failure_stage": "review",
            "proposal": {"action_key": "expand_specialist_scope"},
        },
    )

    assert strategy["enabled"] is True
    assert strategy["use_restricted_probe"] is True
