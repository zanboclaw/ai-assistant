from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class WorkflowProposalContract:
    proposal_id: int
    title: str
    summary: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentRunContract:
    agent_run_id: int
    task_id: int
    role: str
    status: str
    output: dict[str, Any] = field(default_factory=dict)

