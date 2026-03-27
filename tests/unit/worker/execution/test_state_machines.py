from apps.worker.runtime.execution.step_state_machine import (
    StepStatus,
    can_transition_step_status,
    transition_step_status,
)
from apps.worker.runtime.execution.task_state_machine import (
    TaskStatus,
    can_transition_task_status,
    transition_task_status,
)


def test_step_state_machine_allows_mainline_progression():
    assert can_transition_step_status(StepStatus.PENDING, StepStatus.READY) is True
    assert transition_step_status("ready", "running") == StepStatus.RUNNING
    assert transition_step_status(StepStatus.RUNNING, StepStatus.COMPLETED) == StepStatus.COMPLETED


def test_step_state_machine_rejects_invalid_jump():
    try:
        transition_step_status(StepStatus.PENDING, StepStatus.COMPLETED)
    except ValueError as exc:
        assert "invalid step status transition" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected invalid transition")


def test_task_state_machine_allows_recovery_path():
    assert can_transition_task_status(TaskStatus.RUNNING, TaskStatus.RECOVERABLE) is True
    assert transition_task_status(TaskStatus.RECOVERABLE, TaskStatus.PENDING) == TaskStatus.PENDING


def test_task_state_machine_rejects_completed_regression():
    try:
        transition_task_status(TaskStatus.COMPLETED, TaskStatus.PENDING)
    except ValueError as exc:
        assert "invalid task status transition" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected invalid transition")
