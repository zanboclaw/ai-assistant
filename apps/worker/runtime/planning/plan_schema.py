from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PlanSchema:
    source: str
    execution_mode: str
    planned_steps: list[dict[str, Any]] = field(default_factory=list)

