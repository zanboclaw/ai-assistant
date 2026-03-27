from __future__ import annotations

from core.shared.enums import StepStatus


STEP_STATUS_TRANSITIONS: dict[StepStatus, set[StepStatus]] = {
    StepStatus.PENDING: {StepStatus.READY, StepStatus.SKIPPED},
    StepStatus.READY: {StepStatus.RUNNING, StepStatus.SKIPPED},
    StepStatus.RUNNING: {
        StepStatus.BLOCKED,
        StepStatus.WAITING_APPROVAL,
        StepStatus.WAITING_CLARIFICATION,
        StepStatus.FAILED,
        StepStatus.RECOVERABLE,
        StepStatus.COMPLETED,
    },
    StepStatus.BLOCKED: {StepStatus.READY, StepStatus.SKIPPED},
    StepStatus.WAITING_CLARIFICATION: {StepStatus.READY, StepStatus.FAILED},
    StepStatus.WAITING_APPROVAL: {StepStatus.READY, StepStatus.FAILED},
    StepStatus.FAILED: {StepStatus.RECOVERABLE, StepStatus.READY, StepStatus.SKIPPED},
    StepStatus.RECOVERABLE: {StepStatus.READY, StepStatus.SKIPPED, StepStatus.FAILED},
    StepStatus.COMPLETED: set(),
    StepStatus.SKIPPED: set(),
}


def normalize_step_status(status: str | StepStatus) -> StepStatus:
    return status if isinstance(status, StepStatus) else StepStatus(str(status).strip().lower())


def can_transition_step_status(current_status: str | StepStatus, next_status: str | StepStatus) -> bool:
    current = normalize_step_status(current_status)
    target = normalize_step_status(next_status)
    return target in STEP_STATUS_TRANSITIONS[current]


def transition_step_status(current_status: str | StepStatus, next_status: str | StepStatus) -> StepStatus:
    if not can_transition_step_status(current_status, next_status):
        raise ValueError(f"invalid step status transition: {current_status!s} -> {next_status!s}")
    return normalize_step_status(next_status)


__all__ = [
    "STEP_STATUS_TRANSITIONS",
    "StepStatus",
    "can_transition_step_status",
    "normalize_step_status",
    "transition_step_status",
]
