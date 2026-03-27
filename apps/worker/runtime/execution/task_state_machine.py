from __future__ import annotations

from core.shared.enums import TaskStatus


TASK_STATUS_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.RUNNING, TaskStatus.WAITING_CLARIFICATION, TaskStatus.FAILED},
    TaskStatus.RUNNING: {
        TaskStatus.WAITING_APPROVAL,
        TaskStatus.WAITING_CLARIFICATION,
        TaskStatus.RECOVERABLE,
        TaskStatus.FAILED,
        TaskStatus.COMPLETED,
        TaskStatus.INTERRUPTED,
    },
    TaskStatus.WAITING_CLARIFICATION: {TaskStatus.PENDING, TaskStatus.FAILED},
    TaskStatus.WAITING_APPROVAL: {TaskStatus.PENDING, TaskStatus.FAILED},
    TaskStatus.RECOVERABLE: {TaskStatus.PENDING, TaskStatus.FAILED},
    TaskStatus.FAILED: {TaskStatus.RECOVERABLE},
    TaskStatus.COMPLETED: set(),
    TaskStatus.INTERRUPTED: {TaskStatus.PENDING, TaskStatus.FAILED},
}


def normalize_task_status(status: str | TaskStatus) -> TaskStatus:
    return status if isinstance(status, TaskStatus) else TaskStatus(str(status).strip().lower())


def can_transition_task_status(current_status: str | TaskStatus, next_status: str | TaskStatus) -> bool:
    current = normalize_task_status(current_status)
    target = normalize_task_status(next_status)
    return target in TASK_STATUS_TRANSITIONS[current]


def transition_task_status(current_status: str | TaskStatus, next_status: str | TaskStatus) -> TaskStatus:
    if not can_transition_task_status(current_status, next_status):
        raise ValueError(f"invalid task status transition: {current_status!s} -> {next_status!s}")
    return normalize_task_status(next_status)


__all__ = [
    "TASK_STATUS_TRANSITIONS",
    "TaskStatus",
    "can_transition_task_status",
    "normalize_task_status",
    "transition_task_status",
]
