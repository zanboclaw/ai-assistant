from __future__ import annotations


def task_requires_human_attention(task_row: dict) -> bool:
    return str(task_row.get("status") or "") in {"waiting_clarification", "waiting_approval", "recoverable"}

