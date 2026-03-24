from __future__ import annotations

from typing import Any

from core.long_term_memory import search_long_term_memories


def _build_direct_answer(user_input: str, retrieved_memories: list[dict[str, Any]]) -> str:
    normalized = str(user_input or "").strip()
    if retrieved_memories:
        lines = ["快速答复：", ""]
        lines.append(f"你当前的问题是：{normalized}")
        lines.append("")
        lines.append("可直接复用的历史经验：")
        for index, item in enumerate(retrieved_memories[:3], start=1):
            title = str(item.get("title") or "历史记忆").strip()
            content = str(item.get("content") or "").strip()
            lines.append(f"{index}. {title}：{content[:180]}")
        lines.append("")
        lines.append("下一步建议：如果需要审计、回放、审批或产出正式交付，再升级为完整任务。")
        return "\n".join(lines)

    return "\n".join(
        [
            "快速答复：",
            "",
            f"你当前的问题是：{normalized}",
            "当前没有命中高相关的长期记忆，建议先给出更明确的上下文，或升级为正式任务进入完整执行链。",
        ]
    )


def build_fast_path_response(
    cur,
    *,
    user_input: str,
    actor_name: str = "",
    limit: int = 3,
) -> dict[str, Any]:
    retrieved_memories = search_long_term_memories(
        cur,
        user_input,
        actor_name=actor_name or None,
        limit=max(1, min(limit, 5)),
    )
    answer = _build_direct_answer(user_input, retrieved_memories)
    return {
        "mode": "fast_path",
        "answer": answer,
        "memory_context": {
            "retrieval_query": str(user_input or "").strip()[:240],
            "retrieved_memories": retrieved_memories,
            "retrieved_count": len(retrieved_memories),
        },
        "promote_to_task": {
            "recommended": True,
            "reason": "需要审计、回放、审批或正式交付时，建议升级为完整任务。",
        },
    }
