from __future__ import annotations

from typing import Any

from apps.api.intake_task_routes import build_intake_preview_payload, build_memory_context
from apps.api.task_intent_helpers import infer_deliverable_spec, infer_task_intent


def analyze_input(cur, user_input: str, *, session_id: int | None = None, skill_id: str | None = None) -> dict[str, Any]:
    task_intent = infer_task_intent(user_input, skill_id=skill_id)
    deliverable_spec = infer_deliverable_spec(user_input, task_intent)
    memory_context = build_memory_context(cur, user_input)
    return build_intake_preview_payload(
        user_input=user_input,
        session_id=session_id,
        skill_id=skill_id,
        task_intent=task_intent,
        deliverable_spec=deliverable_spec,
        memory_context=memory_context,
    )
