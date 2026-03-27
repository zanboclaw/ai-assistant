from __future__ import annotations


def hydrate_session_context(task_row: dict) -> dict:
    return {
        "session_id": task_row.get("session_id"),
        "task_id": task_row.get("id"),
    }

