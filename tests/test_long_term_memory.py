from core.long_term_memory import (
    build_long_term_memory_key,
    normalize_memory_keywords,
    search_long_term_memories,
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


class MemorySearchCursor:
    def __init__(self, rows):
        self.rows = rows
        self._fetchall = []

    def execute(self, _sql, _params=None):
        self._fetchall = self.rows

    def fetchall(self):
        return list(self._fetchall)


def test_search_long_term_memories_prefers_same_session_and_explains_why():
    cur = MemorySearchCursor(
        [
            {
                "id": 1,
                "memory_key": "a",
                "memory_kind": "pattern_memory",
                "source_session_id": 7,
                "source_task_id": 10,
                "actor_name": "local_admin",
                "title": "发布回滚 Checklist",
                "content": "先执行 healthcheck，再核对 migration。",
                "keywords_json": '["发布","回滚","checklist"]',
                "metadata_json": '{"tags":["发布","回滚"]}',
                "hit_count": 2,
            },
            {
                "id": 2,
                "memory_key": "b",
                "memory_kind": "pattern_memory",
                "source_session_id": 1,
                "source_task_id": 11,
                "actor_name": "other_actor",
                "title": "通用发布记录",
                "content": "记录发布步骤。",
                "keywords_json": '["发布"]',
                "metadata_json": '{}',
                "hit_count": 5,
            },
        ]
    )

    rows = search_long_term_memories(
        cur,
        "发布 回滚 checklist",
        actor_name="local_admin",
        source_session_id=7,
        limit=2,
    )

    assert rows[0]["memory_key"] == "a"
    assert "来自当前 Session 的历史经验" in rows[0]["metadata"]["match_explanation"]
    assert "历史复用 2 次" in rows[0]["metadata"]["match_explanation"]


def test_search_long_term_memories_prefers_exact_title_phrase_over_generic_high_hit_memory():
    cur = MemorySearchCursor(
        [
            {
                "id": 1,
                "memory_key": "generic",
                "memory_kind": "pattern_memory",
                "source_session_id": 2,
                "source_task_id": 20,
                "actor_name": "local_admin",
                "title": "发布经验汇总",
                "content": "这里有很多泛化发布经验。",
                "keywords_json": '["发布"]',
                "metadata_json": '{"tags":["流程"]}',
                "hit_count": 9,
            },
            {
                "id": 2,
                "memory_key": "exact",
                "memory_kind": "pattern_memory",
                "source_session_id": 1,
                "source_task_id": 21,
                "actor_name": "local_admin",
                "title": "发布回滚 Checklist",
                "content": "先确认镜像 tag，再核对 migration 版本。",
                "keywords_json": '["发布","回滚","checklist"]',
                "metadata_json": '{"tags":["发布","回滚"]}',
                "hit_count": 1,
            },
        ]
    )

    rows = search_long_term_memories(cur, "发布 回滚 checklist", actor_name="local_admin", limit=2)

    assert rows[0]["memory_key"] == "exact"
    assert "标题短语直接命中" in rows[0]["metadata"]["match_explanation"]
    assert "标签或元数据命中" in rows[0]["metadata"]["match_explanation"]
