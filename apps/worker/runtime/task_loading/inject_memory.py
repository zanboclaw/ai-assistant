from __future__ import annotations

from apps.worker.task_payloads import augment_user_input_with_memory_context


def inject_memory_into_user_input(user_input: str, task_row: dict) -> str:
    return augment_user_input_with_memory_context(user_input, task_row)

