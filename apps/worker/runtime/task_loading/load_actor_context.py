from __future__ import annotations


def load_actor_context(task_row: dict) -> dict:
    runtime_overrides = task_row.get("runtime_overrides") or {}
    if isinstance(runtime_overrides, str):
        return {"actor_name": str(task_row.get("actor_name") or "local_admin")}
    return {
        "actor_name": str((runtime_overrides or {}).get("actor_name") or task_row.get("actor_name") or "local_admin"),
    }

