from deliverable_runtime import build_deliverable_first_plan
from task_payloads import (
    WEB_SEARCH_QUERY_MAX_LENGTH,
    augment_user_input_with_memory_context,
    sanitize_web_search_query,
)
from worker import normalize_web_search_input


def build_augmented_user_input() -> tuple[str, str]:
    original_user_input = "给我写一篇关于 AI 搜索产品 SEO 策略的文章"
    task_row = {
        "runtime_overrides": {
            "memory_context": {
                "retrieved_memories": [
                    {
                        "memory_kind": "pattern_memory",
                        "title": "历史 SEO 爆款模板",
                        "content": "请优先覆盖品牌词、行业词、交易词，并复用旧项目里的增长打法总结。",
                    }
                ]
            }
        }
    }
    return original_user_input, augment_user_input_with_memory_context(original_user_input, task_row)


def test_sanitize_web_search_query_strips_augmented_memory_context():
    original_user_input, augmented_user_input = build_augmented_user_input()

    query = sanitize_web_search_query(augmented_user_input)

    assert query == original_user_input
    assert "可复用的长期记忆" not in query
    assert "增长打法总结" not in query


def test_build_deliverable_first_plan_uses_sanitized_research_query():
    original_user_input, augmented_user_input = build_augmented_user_input()

    plan = build_deliverable_first_plan(
        augmented_user_input,
        task_intent={"task_type": "content_generation"},
        deliverable_spec={
            "deliverable_type": "copywriting_bundle",
            "expected_sections": ["标题", "正文"],
        },
    )

    assert plan is not None
    assert plan[0]["tool"] == "web_search"
    assert plan[0]["input"]["query"] == original_user_input
    assert "可复用的长期记忆" not in plan[0]["input"]["query"]


def test_normalize_web_search_input_sanitizes_and_truncates_query():
    long_query = (
        "帮我调研 AI 搜索产品的 SEO 竞争策略"
        "\n\n可复用的长期记忆：\n"
        "1. [pattern_memory] 历史 SEO 爆款模板 -> "
        + ("增长打法总结 " * 80)
    )

    normalized = normalize_web_search_input({"q": long_query})

    assert "q" not in normalized
    assert normalized["query"].startswith("帮我调研 AI 搜索产品的 SEO 竞争策略")
    assert "可复用的长期记忆" not in normalized["query"]
    assert len(normalized["query"]) <= WEB_SEARCH_QUERY_MAX_LENGTH
