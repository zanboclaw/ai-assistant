from __future__ import annotations

from typing import Any, Callable


def build_execution_plan(
    cur,
    *,
    task_id: int,
    planner_user_input: str,
    task_context: dict[str, Any],
    intent_plan: dict[str, Any],
    select_task_plan_source: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    return select_task_plan_source(
        cur,
        task_id,
        planner_user_input,
        skill_invocation=task_context.get("skill_invocation") or {},
        task_intent=intent_plan,
        deliverable_spec=task_context.get("deliverable_spec") or {},
        model_route_overrides=task_context.get("model_route_overrides") or {},
    )


__all__ = ["build_execution_plan"]
