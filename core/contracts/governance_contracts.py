from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.shared.enums import ChangeRequestStatus, RiskLevel


@dataclass(slots=True)
class GovernanceDecisionContract:
    actor_name: str
    permission: str
    approved: bool
    reason: str = ""


@dataclass(slots=True)
class AuditEventContract:
    event_type: str
    actor: str
    task_id: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ChangeRequestContract:
    change_request_id: int
    target_type: str
    target_name: str
    status: ChangeRequestStatus = ChangeRequestStatus.DRAFT
    risk_level: RiskLevel = RiskLevel.MEDIUM

