from __future__ import annotations

RUNTIME_SCHEMA_CONTRACT_MIGRATION_ID = "0012_runtime_schema_contract_finalize"

TASK_RUNS_REQUIRED_COLUMNS = (
    "id",
    "user_input",
    "status",
    "result",
    "error_message",
    "current_step",
    "checkpoint_path",
    "session_id",
    "created_by_actor",
    "runtime_overrides",
    "task_intent_json",
    "deliverable_spec_json",
    "validation_report_json",
    "recovery_action_json",
    "created_at",
    "updated_at",
)

TASK_STEPS_REQUIRED_COLUMNS = (
    "id",
    "task_id",
    "step_order",
    "step_name",
    "status",
    "input_payload",
    "output_payload",
    "error_message",
    "tool_name",
    "output_data",
    "error_strategy",
    "run_if",
    "skip_if",
    "retry_count",
    "max_retries",
    "created_at",
    "updated_at",
)

APPROVALS_REQUIRED_COLUMNS = (
    "id",
    "task_id",
    "step_order",
    "step_name",
    "tool_name",
    "input_payload",
    "reason",
    "status",
    "decision_note",
    "created_at",
    "updated_at",
    "decided_at",
)

AUDIT_LOGS_REQUIRED_COLUMNS = (
    "id",
    "task_id",
    "event_type",
    "actor",
    "details",
    "created_at",
)

TASK_TRACES_REQUIRED_COLUMNS = (
    "id",
    "trace_id",
    "task_run_id",
    "status",
    "plan_source",
    "error_summary",
    "input_summary",
    "metadata_json",
    "started_at",
    "ended_at",
    "created_at",
    "updated_at",
)

STEP_TRACES_REQUIRED_COLUMNS = (
    "id",
    "trace_id",
    "task_trace_id",
    "task_run_id",
    "task_step_id",
    "step_order",
    "step_name",
    "tool_name",
    "status",
    "input_snapshot",
    "output_snapshot",
    "error_summary",
    "retry_count",
    "max_retries",
    "started_at",
    "ended_at",
    "created_at",
)

MODEL_TRACES_REQUIRED_COLUMNS = (
    "id",
    "trace_id",
    "task_run_id",
    "task_step_id",
    "step_trace_id",
    "route_name",
    "provider",
    "model_name",
    "prompt_version",
    "prompt_hash",
    "status",
    "request_excerpt",
    "response_excerpt",
    "error_summary",
    "metadata_json",
    "started_at",
    "ended_at",
    "created_at",
)

TOOL_TRACES_REQUIRED_COLUMNS = (
    "id",
    "trace_id",
    "task_run_id",
    "task_step_id",
    "step_trace_id",
    "tool_name",
    "tool_args_hash",
    "status",
    "input_snapshot",
    "output_snapshot",
    "error_summary",
    "metadata_json",
    "started_at",
    "ended_at",
    "created_at",
)

SKILL_TRACES_REQUIRED_COLUMNS = (
    "id",
    "trace_id",
    "task_run_id",
    "task_step_id",
    "skill_id",
    "skill_version",
    "status",
    "input_snapshot",
    "output_snapshot",
    "error_summary",
    "metadata_json",
    "started_at",
    "ended_at",
    "created_at",
)

RETRIEVAL_TRACES_REQUIRED_COLUMNS = (
    "id",
    "trace_id",
    "task_run_id",
    "task_step_id",
    "retrieval_scope",
    "status",
    "query_text",
    "result_count",
    "error_summary",
    "metadata_json",
    "started_at",
    "ended_at",
    "created_at",
)

SKILLS_REQUIRED_COLUMNS = (
    "skill_id",
    "display_name",
    "description",
    "status",
    "latest_version",
    "entrypoint_kind",
    "created_at",
    "updated_at",
)

SKILL_VERSIONS_REQUIRED_COLUMNS = (
    "id",
    "skill_id",
    "version",
    "package_format",
    "package_source",
    "description",
    "package_body",
    "created_at",
)

AGENT_RUNS_REQUIRED_COLUMNS = (
    "id",
    "task_run_id",
    "parent_agent_run_id",
    "role",
    "status",
    "attempt",
    "brief_artifact_id",
    "output_artifact_id",
    "review_artifact_id",
    "execution_mode",
    "execution_request_json",
    "source_task_run_id",
    "assigned_step_orders_json",
    "assigned_model",
    "assigned_tool_profile",
    "error_summary",
    "cost_tokens_in",
    "cost_tokens_out",
    "cost_usd_estimate",
    "created_at",
    "updated_at",
    "started_at",
    "completed_at",
)

AGENT_MESSAGES_REQUIRED_COLUMNS = (
    "id",
    "task_run_id",
    "agent_run_id",
    "sender_role",
    "recipient_role",
    "message_type",
    "payload_json",
    "created_at",
)

AGENT_ARTIFACTS_REQUIRED_COLUMNS = (
    "id",
    "task_run_id",
    "agent_run_id",
    "artifact_type",
    "summary",
    "content_json",
    "version",
    "created_at",
)

EVALUATOR_RUNS_REQUIRED_COLUMNS = (
    "id",
    "task_run_id",
    "manager_agent_run_id",
    "reviewer_agent_run_id",
    "final_artifact_id",
    "review_artifact_id",
    "evaluator_kind",
    "status",
    "decision",
    "score",
    "failure_reason",
    "failure_stage",
    "criteria_json",
    "step_stats_json",
    "proposal_json",
    "summary",
    "recommendation",
    "source",
    "created_at",
)

SESSIONS_REQUIRED_COLUMNS = (
    "id",
    "name",
    "description",
    "created_at",
    "updated_at",
)

SESSION_MEMORIES_REQUIRED_COLUMNS = (
    "id",
    "session_id",
    "category",
    "content",
    "importance",
    "source_task_id",
    "created_at",
    "updated_at",
)

SESSION_STATES_REQUIRED_COLUMNS = (
    "session_id",
    "summary_text",
    "preferences",
    "open_loops",
    "created_at",
    "updated_at",
)

SESSION_REVIEWS_REQUIRED_COLUMNS = (
    "id",
    "session_id",
    "review_kind",
    "summary_text",
    "highlights",
    "open_loops",
    "created_at",
)

CHANGE_REQUESTS_REQUIRED_COLUMNS = (
    "id",
    "target_type",
    "target_key",
    "proposed_payload",
    "rationale",
    "status",
    "requested_by_actor",
    "reviewed_by_actor",
    "decision_note",
    "applied_by_actor",
    "proposal_kind",
    "source_change_request_id",
    "source_workflow_proposal_id",
    "shadow_validation_status",
    "shadow_validation_report",
    "shadow_validation_at",
    "baseline_payload",
    "payload_patch",
    "patch_summary",
    "rollback_payload",
    "rollback_ready",
    "rollback_note",
    "acceptance_status",
    "acceptance_report",
    "acceptance_at",
    "auto_rollback_change_request_id",
    "auto_rollback_at",
    "created_at",
    "reviewed_at",
    "applied_at",
)

RUNTIME_CORE_TABLE_CONTRACTS = {
    "task_runs": TASK_RUNS_REQUIRED_COLUMNS,
    "task_steps": TASK_STEPS_REQUIRED_COLUMNS,
    "approvals": APPROVALS_REQUIRED_COLUMNS,
}

TRACE_TABLE_CONTRACTS = {
    "task_traces": TASK_TRACES_REQUIRED_COLUMNS,
    "step_traces": STEP_TRACES_REQUIRED_COLUMNS,
    "model_traces": MODEL_TRACES_REQUIRED_COLUMNS,
    "tool_traces": TOOL_TRACES_REQUIRED_COLUMNS,
    "skill_traces": SKILL_TRACES_REQUIRED_COLUMNS,
    "retrieval_traces": RETRIEVAL_TRACES_REQUIRED_COLUMNS,
}

SKILL_TABLE_CONTRACTS = {
    "skills": SKILLS_REQUIRED_COLUMNS,
    "skill_versions": SKILL_VERSIONS_REQUIRED_COLUMNS,
}

AGENT_TABLE_CONTRACTS = {
    "agent_runs": AGENT_RUNS_REQUIRED_COLUMNS,
    "agent_messages": AGENT_MESSAGES_REQUIRED_COLUMNS,
    "agent_artifacts": AGENT_ARTIFACTS_REQUIRED_COLUMNS,
}

SESSION_TABLE_CONTRACTS = {
    "sessions": SESSIONS_REQUIRED_COLUMNS,
    "session_memories": SESSION_MEMORIES_REQUIRED_COLUMNS,
    "session_states": SESSION_STATES_REQUIRED_COLUMNS,
    "session_reviews": SESSION_REVIEWS_REQUIRED_COLUMNS,
}
