from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.shared.enums import RiskLevel, StepStatus, TaskStatus


@dataclass(slots=True)
class RecoveryActionContract:
    action: str
    label: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StepContract:
    step_id: int | None
    step_order: int
    step_name: str
    status: StepStatus = StepStatus.PENDING
    tool_name: str = ""
    checkpoint: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TaskContract:
    task_id: int
    user_input: str
    status: TaskStatus = TaskStatus.PENDING
    risk_level: RiskLevel = RiskLevel.LOW
    session_id: int | None = None
    steps: list[StepContract] = field(default_factory=list)
    runtime_overrides: dict[str, Any] = field(default_factory=dict)

