from __future__ import annotations

from apps.worker.task_payloads import (
    extract_deliverable_spec,
    extract_memory_context,
    extract_recovery_action,
    extract_task_intent,
    extract_task_model_route_overrides,
    extract_task_skill_invocation,
    extract_validation_report,
)


def load_task_runtime_context(task_row: dict) -> dict:
    return {
        "task": task_row,
        "task_id": task_row.get("id"),
        "user_input": str(task_row.get("user_input") or ""),
        "session_id": task_row.get("session_id"),
        "task_intent": extract_task_intent(task_row),
        "deliverable_spec": extract_deliverable_spec(task_row),
        "memory_context": extract_memory_context(task_row),
        "model_route_overrides": extract_task_model_route_overrides(task_row),
        "skill_invocation": extract_task_skill_invocation(task_row),
        "validation_report": extract_validation_report(task_row),
        "recovery_action": extract_recovery_action(task_row),
    }
