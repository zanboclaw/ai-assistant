from pydantic import BaseModel
from typing import Any


class TaskCreate(BaseModel):
    user_input: str
    session_id: int | None = None
    skill_id: str | None = None
    skill_version: str | None = None
    skill_args: dict[str, Any] | None = None


class AgentBootstrapRequest(BaseModel):
    objective: str = ""
    specialist_count: int = 2
    include_reviewer: bool = True
    note: str = ""


class AgentFinalizeRequest(BaseModel):
    summary: str = ""
    note: str = ""
    reviewer_decision: str = "auto"
    allow_retry: bool = False


class AgentExecuteRequest(BaseModel):
    note: str = ""
    force_rerun: bool = False
    subtask_type: str = "readonly_step_digest"
    source_kind: str = ""
    source_path: str = ""
    source_json_path: str = ""
    dir_limit: int = 20


class SessionCreate(BaseModel):
    name: str
    description: str = ""


class SessionMemoryCreate(BaseModel):
    category: str
    content: str
    importance: int = 3
    source_task_id: int | None = None


class SessionStateUpdate(BaseModel):
    summary_text: str = ""
    preferences: list[str] = []
    open_loops: list[str] = []


class SessionReviewCreate(BaseModel):
    review_kind: str = "manual"
    note: str = ""


class DailyReviewRunRequest(BaseModel):
    review_kind: str = "daily"
    note: str = ""
    session_limit: int = 20
    active_within_hours: int = 24
    force: bool = False


class ApprovalDecision(BaseModel):
    note: str = ""


class TaskResumeRequest(BaseModel):
    note: str = ""
    from_step: int | None = None


class TaskInterruptRequest(BaseModel):
    note: str = ""


class TaskClarifyRequest(BaseModel):
    clarification: str
    note: str = ""


class RiskPolicyUpdate(BaseModel):
    policy_value: Any


class AccessQuotaUpdate(BaseModel):
    daily_task_limit: int
    active_task_limit: int


class ToolRegistryUpdate(BaseModel):
    enabled: bool
    risk_level: str
    provider_type: str = "builtin"
    transport: str = "local"
    server_name: str = ""
    provider_config: dict[str, Any] = {}
    approval_required: bool = False
    description: str = ""


class ModelRouteUpdate(BaseModel):
    provider: str
    enabled: bool
    model_name: str
    temperature: float
    max_tokens: int
    description: str = ""


class ModelProviderUpdate(BaseModel):
    driver: str
    base_url: str
    api_key_env: str
    enabled: bool
    description: str = ""


class ChangeRequestCreate(BaseModel):
    target_type: str
    target_key: str
    proposed_payload: dict[str, Any]
    rationale: str = ""


class ChangeRequestDecision(BaseModel):
    note: str = ""


class WorkflowProposalBridgeRequest(BaseModel):
    target_type: str
    target_key: str
    proposed_payload: dict[str, Any]
    rationale: str = ""


class WorkflowProposalShadowValidationRequest(BaseModel):
    note: str = ""
    shadow_user_input: str = ""
    await_completion: bool = False
    timeout_seconds: int = 45
    poll_interval_seconds: float = 1.0
    use_suggested_candidate: bool = True
    candidate_target_type: str = ""
    candidate_target_key: str = ""
    candidate_payload: dict[str, Any] | None = None


class AccessActorUpdate(BaseModel):
    role: str
    description: str = ""


class SkillImportRequest(BaseModel):
    source_path: str
    activate: bool = True
