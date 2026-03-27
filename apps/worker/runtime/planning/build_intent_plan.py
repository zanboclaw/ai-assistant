from __future__ import annotations

from typing import Any


def build_intent_plan(task_context: dict[str, Any]) -> dict[str, Any]:
    task_intent = dict(task_context.get("task_intent") or {})
    deliverable_spec = dict(task_context.get("deliverable_spec") or {})
    skill_invocation = dict(task_context.get("skill_invocation") or {})
    return {
        "goal_summary": str(task_intent.get("goal_summary") or task_context.get("user_input") or "").strip(),
        "task_type": str(task_intent.get("task_type") or "unknown").strip() or "unknown",
        "needs_clarification": bool(task_intent.get("needs_clarification"))
        or bool(((deliverable_spec.get("clarify") or {}).get("blocking"))),
        "deliverable_type": str(deliverable_spec.get("deliverable_type") or "unknown").strip() or "unknown",
        "skill_id": str(skill_invocation.get("skill_id") or "").strip(),
        "memory_hits": len(list((task_context.get("memory_context") or {}).get("retrieved_memories") or [])),
    }
