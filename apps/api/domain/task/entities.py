from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.shared.enums import TaskStatus


@dataclass(slots=True)
class TaskEntity:
    task_id: int
    user_input: str
    status: TaskStatus = TaskStatus.PENDING
    session_id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

