from core.contracts.task_contracts import RecoveryActionContract, StepContract, TaskContract
from core.shared.enums import StepStatus, TaskStatus


def test_task_contract_defaults_are_stable():
    step = StepContract(step_id=1, step_order=1, step_name="plan", status=StepStatus.READY)
    task = TaskContract(task_id=42, user_input="整理发布方案", status=TaskStatus.RUNNING, steps=[step])

    assert task.task_id == 42
    assert task.status == TaskStatus.RUNNING
    assert task.steps[0].status == StepStatus.READY


def test_recovery_action_contract_carries_details():
    action = RecoveryActionContract(action="retry_current_step", label="重试当前步骤", details={"step_id": 3})

    assert action.action == "retry_current_step"
    assert action.details["step_id"] == 3

