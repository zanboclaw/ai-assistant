import json
import os
from typing import Any


def parse_maybe_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except Exception:
            return value
    return value


def serialize_tool_registry_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "tool_name": row["tool_name"],
        "enabled": bool(row["enabled"]),
        "risk_level": row["risk_level"],
        "description": row["description"] or "",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def serialize_model_route_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "route_name": row["route_name"],
        "provider": row["provider"],
        "model_name": row["model_name"],
        "temperature": float(row["temperature"]),
        "max_tokens": int(row["max_tokens"]),
        "enabled": bool(row["enabled"]),
        "description": row["description"] or "",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def serialize_model_provider_row(row: dict[str, Any]) -> dict[str, Any]:
    api_key_env = str(row["api_key_env"])
    return {
        "provider_name": row["provider_name"],
        "driver": row["driver"],
        "base_url": row["base_url"],
        "api_key_env": api_key_env,
        "configured": bool(os.environ.get(api_key_env)),
        "enabled": bool(row["enabled"]),
        "description": row.get("description") or "",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def serialize_access_quota_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "actor_name": row["actor_name"],
        "daily_task_limit": int(row["daily_task_limit"]),
        "active_task_limit": int(row["active_task_limit"]),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def serialize_access_actor_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "actor_name": row["actor_name"],
        "role": row["role"],
        "description": row["description"] or "",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def serialize_session_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "description": row.get("description"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def serialize_session_memory_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "session_id": row.get("session_id"),
        "category": row.get("category"),
        "content": row.get("content"),
        "importance": row.get("importance"),
        "source_task_id": row.get("source_task_id"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def serialize_session_state_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": row.get("session_id"),
        "summary_text": row.get("summary_text") or "",
        "preferences": parse_maybe_json(row.get("preferences")) or [],
        "open_loops": parse_maybe_json(row.get("open_loops")) or [],
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def serialize_session_review_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "session_id": row.get("session_id"),
        "review_kind": row.get("review_kind"),
        "summary_text": row.get("summary_text") or "",
        "highlights": parse_maybe_json(row.get("highlights")) or [],
        "open_loops": parse_maybe_json(row.get("open_loops")) or [],
        "created_at": row.get("created_at"),
    }


def serialize_agent_run_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "task_run_id": row.get("task_run_id"),
        "parent_agent_run_id": row.get("parent_agent_run_id"),
        "role": row.get("role"),
        "status": row.get("status"),
        "attempt": int(row.get("attempt") or 1),
        "brief_artifact_id": row.get("brief_artifact_id"),
        "output_artifact_id": row.get("output_artifact_id"),
        "review_artifact_id": row.get("review_artifact_id"),
        "execution_mode": row.get("execution_mode") or "",
        "execution_request": parse_maybe_json(row.get("execution_request_json")),
        "source_task_run_id": row.get("source_task_run_id"),
        "assigned_step_orders": parse_maybe_json(row.get("assigned_step_orders_json")) or [],
        "assigned_model": row.get("assigned_model") or "",
        "assigned_tool_profile": row.get("assigned_tool_profile") or "",
        "error_summary": row.get("error_summary") or "",
        "cost_tokens_in": int(row.get("cost_tokens_in") or 0),
        "cost_tokens_out": int(row.get("cost_tokens_out") or 0),
        "cost_usd_estimate": float(row.get("cost_usd_estimate") or 0),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "started_at": row.get("started_at"),
        "completed_at": row.get("completed_at"),
    }


def serialize_agent_message_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "task_run_id": row.get("task_run_id"),
        "agent_run_id": row.get("agent_run_id"),
        "sender_role": row.get("sender_role"),
        "recipient_role": row.get("recipient_role"),
        "message_type": row.get("message_type"),
        "payload": parse_maybe_json(row.get("payload_json")),
        "created_at": row.get("created_at"),
    }


def serialize_agent_artifact_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "task_run_id": row.get("task_run_id"),
        "agent_run_id": row.get("agent_run_id"),
        "artifact_type": row.get("artifact_type"),
        "summary": row.get("summary") or "",
        "content": parse_maybe_json(row.get("content_json")),
        "version": int(row.get("version") or 1),
        "created_at": row.get("created_at"),
    }


def serialize_evaluator_run_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "task_run_id": row.get("task_run_id"),
        "manager_agent_run_id": row.get("manager_agent_run_id"),
        "reviewer_agent_run_id": row.get("reviewer_agent_run_id"),
        "final_artifact_id": row.get("final_artifact_id"),
        "review_artifact_id": row.get("review_artifact_id"),
        "evaluator_kind": row.get("evaluator_kind") or "",
        "status": row.get("status") or "",
        "decision": row.get("decision") or "",
        "score": int(row.get("score") or 0),
        "failure_reason": row.get("failure_reason") or "none",
        "failure_stage": row.get("failure_stage") or "none",
        "criteria": parse_maybe_json(row.get("criteria_json")) or [],
        "step_stats": parse_maybe_json(row.get("step_stats_json")) or {},
        "workflow_proposal": parse_maybe_json(row.get("proposal_json")) or {},
        "summary": row.get("summary") or "",
        "recommendation": row.get("recommendation") or "",
        "source": row.get("source") or "",
        "created_at": row.get("created_at"),
    }


def serialize_workflow_proposal(
    *,
    evaluator_run: dict[str, Any],
    proposal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    proposal = proposal or dict((evaluator_run or {}).get("workflow_proposal") or {})
    return {
        "id": int((evaluator_run or {}).get("id") or 0),
        "evaluator_run_id": (evaluator_run or {}).get("id"),
        "task_run_id": (evaluator_run or {}).get("task_run_id"),
        "decision": (evaluator_run or {}).get("decision") or "",
        "score": int((evaluator_run or {}).get("score") or 0),
        "failure_reason": (evaluator_run or {}).get("failure_reason") or "none",
        "failure_stage": (evaluator_run or {}).get("failure_stage") or "none",
        "status": proposal.get("status") or "suggested",
        "priority": proposal.get("priority") or "",
        "target_surface": proposal.get("target_surface") or "",
        "action_key": proposal.get("action_key") or "",
        "title": proposal.get("title") or "",
        "rationale": proposal.get("rationale") or ((evaluator_run or {}).get("recommendation") or ""),
        "action_payload": proposal.get("action_payload") or {},
        "next_strategy": proposal.get("next_strategy") or "",
        "auto_apply_eligible": bool(proposal.get("auto_apply_eligible")),
        "source": (evaluator_run or {}).get("source") or "",
        "created_at": (evaluator_run or {}).get("created_at"),
        "proposal": proposal,
    }
