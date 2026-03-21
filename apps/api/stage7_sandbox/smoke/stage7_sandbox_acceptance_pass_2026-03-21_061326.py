#!/usr/bin/env python3
"""Minimal CLI for interacting with the AI Assistant API."""

from __future__ import annotations

import argparse
import json
import os
import sys

import requests

API_BASE = os.environ.get("API_BASE", "http://localhost:8000")
API_ACTOR = os.environ.get("AI_ACTOR", "").strip()


def _colored(text: str, color: str) -> str:
    return text


def _print_json(data: object | str | None) -> None:
    if data is None:
        print("no data returned")
        return
    if isinstance(data, str):
        print(data)
        return
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _call(method: str, path: str, **kwargs) -> object | None:
    url = f"{API_BASE.rstrip('/')}/{path.lstrip('/')}"
    headers = dict(kwargs.pop("headers", {}) or {})
    if API_ACTOR:
        headers["X-Actor-Name"] = API_ACTOR
    resp = requests.request(method, url, headers=headers, **kwargs)
    resp.raise_for_status()
    if not resp.text:
        return None
    try:
        return resp.json()
    except ValueError:
        return resp.text


def _list_tasks(_: argparse.Namespace) -> None:
    data = _call("GET", "/tasks")
    _print_json(data)


def _create_task(args: argparse.Namespace) -> None:
    payload = {"user_input": args.input, "session_id": args.session_id}
    data = _call("POST", "/tasks", json=payload)
    _print_json(data)


def _show_task(args: argparse.Namespace) -> None:
    data = _call("GET", f"/tasks/{args.task_id}")
    _print_json(data)


def _show_steps(args: argparse.Namespace) -> None:
    data = _call("GET", f"/tasks/{args.task_id}/steps")
    _print_json(data)


def _show_checkpoint(args: argparse.Namespace) -> None:
    data = _call("GET", f"/tasks/{args.task_id}/checkpoint")
    _print_json(data)


def _resume_task(args: argparse.Namespace) -> None:
    payload = {"note": args.note or "", "from_step": args.from_step}
    data = _call("POST", f"/tasks/{args.task_id}/resume", json=payload)
    _print_json(data)


def _interrupt_task(args: argparse.Namespace) -> None:
    payload = {"note": args.note or ""}
    data = _call("POST", f"/tasks/{args.task_id}/interrupt", json=payload)
    _print_json(data)


def _list_approvals(args: argparse.Namespace) -> None:
    if args.task_id:
        data = _call("GET", f"/tasks/{args.task_id}/approvals")
    else:
        params = {"status": args.status} if args.status else {}
        data = _call("GET", "/approvals", params=params)
    _print_json(data)


def _decide_approval(args: argparse.Namespace) -> None:
    path = "approve" if args.approve else "reject"
    payload = {"note": args.note or ""}
    data = _call("POST", f"/approvals/{args.approval_id}/{path}", json=payload)
    _print_json(data)


def _list_risk_policies(_: argparse.Namespace) -> None:
    data = _call("GET", "/risk-policies")
    _print_json(data)


def _show_runtime_metadata(_: argparse.Namespace) -> None:
    data = _call("GET", "/runtime-metadata")
    _print_json(data)


def _list_agent_runs(args: argparse.Namespace) -> None:
    params = {}
    if args.task_id is not None:
        params["task_id"] = args.task_id
    if args.role:
        params["role"] = args.role
    if args.status:
        params["status"] = args.status
    data = _call("GET", "/agent-runs", params=params)
    _print_json(data)


def _show_agent_run(args: argparse.Namespace) -> None:
    data = _call("GET", f"/agent-runs/{args.agent_run_id}")
    _print_json(data)


def _show_task_agent_run_summary(args: argparse.Namespace) -> None:
    data = _call("GET", f"/tasks/{args.task_id}/agent-runs/summary")
    if not getattr(args, "compact", False):
        _print_json(data)
        return
    latest_final = (data or {}).get("latest_final_artifact") or {}
    latest_evaluator = (data or {}).get("latest_evaluator") or {}
    latest_workflow_proposal = (data or {}).get("latest_workflow_proposal") or {}
    print("\t".join([
        str((data or {}).get("task_id") or args.task_id),
        str((data or {}).get("implementation_status") or "-"),
        str((data or {}).get("execution_backend") or "-"),
        str(latest_evaluator.get("source") or "-"),
        str(latest_workflow_proposal.get("action_key") or "-"),
        str((data or {}).get("manager", {}).get("status") or "-"),
        str((data or {}).get("recommended_action") or "none"),
        str((data or {}).get("awaiting_role") or "-"),
        str((data or {}).get("blocking_reason") or "-"),
        str((data or {}).get("latest_reviewer_decision") or "-"),
        str((data or {}).get("latest_failure_reason") or "-"),
        str((data or {}).get("latest_failure_stage") or "-"),
        str((data or {}).get("latest_decision_source") or "-"),
        str((data or {}).get("latest_next_strategy") or "-"),
        str(latest_final.get("version") or 0),
        str(latest_final.get("quality_score") if latest_final.get("quality_score") is not None else "-"),
    ]))


def _list_task_stage5_status(args: argparse.Namespace) -> None:
    params = {}
    if args.session_id is not None:
        params["session_id"] = args.session_id
    params["include_stage5_summary"] = "true"
    rows = _call("GET", "/tasks", params=params) or []
    print("task_id\ttask_status\timplementation_status\texecution_backend\tlatest_evaluator.source\tlatest_workflow_proposal.action_key\tmanager_status\trecommended_action\tawaiting_role\tblocking_reason\treviewer_decision\tfailure_reason\tfailure_stage\tdecision_source\tnext_strategy\tfinal_version\tquality_score")
    for row in rows:
        stage5 = row.get("stage5") or {}
        latest_final = stage5.get("latest_final_artifact") or {}
        manager = stage5.get("manager") or {}
        latest_evaluator = stage5.get("latest_evaluator") or {}
        latest_workflow_proposal = stage5.get("latest_workflow_proposal") or {}
        print("\t".join([
            str(row.get("id") or ""),
            str(row.get("status") or "-"),
            str(stage5.get("implementation_status") or "-"),
            str(stage5.get("execution_backend") or "-"),
            str(latest_evaluator.get("source") or "-"),
            str(latest_workflow_proposal.get("action_key") or "-"),
            str(manager.get("status") or "-"),
            str(stage5.get("recommended_action") or "none"),
            str(stage5.get("awaiting_role") or "-"),
            str(stage5.get("blocking_reason") or "-"),
            str(stage5.get("latest_reviewer_decision") or "-"),
            str(stage5.get("latest_failure_reason") or "-"),
            str(stage5.get("latest_failure_stage") or "-"),
            str(stage5.get("latest_decision_source") or "-"),
            str(stage5.get("latest_next_strategy") or "-"),
            str(latest_final.get("version") or 0),
            str(latest_final.get("quality_score") if latest_final.get("quality_score") is not None else "-"),
        ]))


def _list_agent_run_messages(args: argparse.Namespace) -> None:
    params = {"limit": args.limit} if args.limit else {}
    data = _call("GET", f"/agent-runs/{args.agent_run_id}/messages", params=params)
    _print_json(data)


def _list_agent_run_artifacts(args: argparse.Namespace) -> None:
    params = {"limit": args.limit} if args.limit else {}
    data = _call("GET", f"/agent-runs/{args.agent_run_id}/artifacts", params=params)
    _print_json(data)


def _bootstrap_task_agent_runs(args: argparse.Namespace) -> None:
    payload = {
        "objective": args.objective or "",
        "specialist_count": args.specialist_count,
        "include_reviewer": not bool(args.no_reviewer),
        "note": args.note or "",
    }
    data = _call("POST", f"/tasks/{args.task_id}/agent-runs/bootstrap-demo", json=payload)
    _print_json(data)


def _execute_task_agent_runs(args: argparse.Namespace) -> None:
    payload = {
        "note": args.note or "",
        "force_rerun": bool(args.force_rerun),
    }
    data = _call("POST", f"/tasks/{args.task_id}/agent-runs/execute-demo", json=payload)
    _print_json(data)


def _execute_task_agent_runs_via_worker(args: argparse.Namespace) -> None:
    payload = {
        "note": args.note or "",
        "force_rerun": bool(args.force_rerun),
        "subtask_type": args.subtask_type,
        "source_kind": args.source_kind or "",
        "source_path": args.source_path or "",
        "source_json_path": args.source_json_path or "",
        "dir_limit": args.dir_limit,
    }
    data = _call("POST", f"/tasks/{args.task_id}/agent-runs/execute-worker-demo", json=payload)
    _print_json(data)


def _finalize_task_agent_runs(args: argparse.Namespace) -> None:
    payload = {
        "summary": args.summary or "",
        "note": args.note or "",
        "reviewer_decision": args.reviewer_decision,
        "allow_retry": bool(args.allow_retry),
    }
    data = _call("POST", f"/tasks/{args.task_id}/agent-runs/finalize-demo", json=payload)
    _print_json(data)


def _list_evaluator_runs(args: argparse.Namespace) -> None:
    params = {"limit": args.limit}
    if args.task_id is not None:
        params["task_id"] = args.task_id
    data = _call("GET", "/evaluator-runs", params=params)
    _print_json(data)


def _show_latest_task_evaluator(args: argparse.Namespace) -> None:
    data = _call("GET", f"/tasks/{args.task_id}/evaluator-runs/latest")
    if not getattr(args, "compact", False):
        _print_json(data)
        return
    print("\t".join([
        str(data.get("task_run_id") or args.task_id),
        str(data.get("decision") or "-"),
        str(data.get("score") if data.get("score") is not None else "-"),
        str(data.get("failure_reason") or "-"),
        str(data.get("failure_stage") or "-"),
        str(((data.get("workflow_proposal") or {}).get("action_key")) or "-"),
        str(data.get("recommendation") or "-"),
        str(data.get("source") or "-"),
        str(data.get("created_at") or "-"),
    ]))


def _show_evaluator_run(args: argparse.Namespace) -> None:
    data = _call("GET", f"/evaluator-runs/{args.evaluator_run_id}")
    _print_json(data)


def _list_workflow_proposals(args: argparse.Namespace) -> None:
    params = {"limit": args.limit}
    if args.task_id is not None:
        params["task_id"] = args.task_id
    if args.action_key:
        params["action_key"] = args.action_key
    if args.priority:
        params["priority"] = args.priority
    data = _call("GET", "/workflow-proposals", params=params)
    _print_json(data)


def _show_task_workflow_proposals(args: argparse.Namespace) -> None:
    data = _call("GET", f"/tasks/{args.task_id}/workflow-proposals", params={"limit": args.limit})
    _print_json(data)


def _show_latest_task_workflow_proposal(args: argparse.Namespace) -> None:
    data = _call("GET", f"/tasks/{args.task_id}/workflow-proposals/latest")
    if not getattr(args, "compact", False):
        _print_json(data)
        return
    print("\t".join([
        str(data.get("task_run_id") or args.task_id),
        str(data.get("action_key") or "-"),
        str(data.get("priority") or "-"),
        str(data.get("target_surface") or "-"),
        str(data.get("failure_reason") or "-"),
        str(data.get("failure_stage") or "-"),
        str(data.get("created_at") or "-"),
    ]))


def _show_workflow_proposal(args: argparse.Namespace) -> None:
    data = _call("GET", f"/workflow-proposals/{args.proposal_id}")
    _print_json(data)


def _show_workflow_proposal_shadow_validation(args: argparse.Namespace) -> None:
    data = _call(
        "GET",
        f"/workflow-proposals/{args.proposal_id}/shadow-validation",
        params={"history_limit": args.history_limit},
    )
    _print_json(data)


def _preview_workflow_proposal_change_request_draft(args: argparse.Namespace) -> None:
    data = _call("GET", f"/workflow-proposals/{args.proposal_id}/change-request-draft")
    _print_json(data)


def _create_change_request_from_workflow_proposal(args: argparse.Namespace) -> None:
    payload = {
        "target_type": args.target_type,
        "target_key": args.target_key,
        "proposed_payload": json.loads(args.proposed_payload),
        "rationale": args.rationale or "",
    }
    data = _call("POST", f"/workflow-proposals/{args.proposal_id}/change-request-draft", json=payload)
    _print_json(data)


def _shadow_validate_workflow_proposal(args: argparse.Namespace) -> None:
    payload = {
        "note": args.note or "",
        "shadow_user_input": args.shadow_user_input or "",
        "await_completion": bool(args.await_completion),
        "timeout_seconds": int(args.timeout_seconds),
        "poll_interval_seconds": float(args.poll_interval_seconds),
        "use_suggested_candidate": bool(args.use_suggested_candidate),
        "candidate_target_type": args.candidate_target_type or "",
        "candidate_target_key": args.candidate_target_key or "",
        "candidate_payload": json.loads(args.candidate_payload) if args.candidate_payload else None,
    }
    data = _call("POST", f"/workflow-proposals/{args.proposal_id}/shadow-validate", json=payload)
    _print_json(data)


def _shadow_validate_change_request(args: argparse.Namespace) -> None:
    payload = {
        "note": args.note or "",
        "shadow_user_input": args.shadow_user_input or "",
        "await_completion": bool(args.await_completion),
        "timeout_seconds": int(args.timeout_seconds),
        "poll_interval_seconds": float(args.poll_interval_seconds),
    }
    data = _call("POST", f"/change-requests/{args.change_request_id}/shadow-validate", json=payload)
    _print_json(data)


def _list_sessions(_: argparse.Namespace) -> None:
    data = _call("GET", "/sessions")
    _print_json(data)


def _create_session(args: argparse.Namespace) -> None:
    payload = {"name": args.name, "description": args.description or ""}
    data = _call("POST", "/sessions", json=payload)
    _print_json(data)


def _show_session(args: argparse.Namespace) -> None:
    data = _call("GET", f"/sessions/{args.session_id}")
    _print_json(data)


def _show_session_tasks(args: argparse.Namespace) -> None:
    data = _call("GET", f"/sessions/{args.session_id}/tasks")
    _print_json(data)


def _show_session_summary(args: argparse.Namespace) -> None:
    data = _call("GET", f"/sessions/{args.session_id}/summary")
    _print_json(data)


def _show_session_health(args: argparse.Namespace) -> None:
    data = _call("GET", f"/sessions/{args.session_id}/health")
    _print_json(data)


def _add_session_memory(args: argparse.Namespace) -> None:
    payload = {
        "category": args.category,
        "content": args.content,
        "importance": args.importance,
        "source_task_id": args.source_task_id,
    }
    data = _call("POST", f"/sessions/{args.session_id}/memories", json=payload)
    _print_json(data)


def _list_session_memories(args: argparse.Namespace) -> None:
    params = {}
    if args.category:
        params["category"] = args.category
    if args.limit:
        params["limit"] = args.limit
    data = _call("GET", f"/sessions/{args.session_id}/memories", params=params)
    _print_json(data)


def _show_session_state(args: argparse.Namespace) -> None:
    data = _call("GET", f"/sessions/{args.session_id}/state")
    _print_json(data)


def _set_session_state(args: argparse.Namespace) -> None:
    preferences = json.loads(args.preferences) if args.preferences else []
    open_loops = json.loads(args.open_loops) if args.open_loops else []
    payload = {
        "summary_text": args.summary_text or "",
        "preferences": preferences,
        "open_loops": open_loops,
    }
    data = _call("PUT", f"/sessions/{args.session_id}/state", json=payload)
    _print_json(data)


def _rebuild_session_state(args: argparse.Namespace) -> None:
    data = _call("POST", f"/sessions/{args.session_id}/state/rebuild")
    _print_json(data)


def _create_session_review(args: argparse.Namespace) -> None:
    payload = {
        "review_kind": args.review_kind or "manual",
        "note": args.note or "",
    }
    data = _call("POST", f"/sessions/{args.session_id}/reviews", json=payload)
    _print_json(data)


def _list_session_reviews(args: argparse.Namespace) -> None:
    params = {"limit": args.limit} if args.limit else {}
    data = _call("GET", f"/sessions/{args.session_id}/reviews", params=params)
    _print_json(data)


def _run_daily_reviews(args: argparse.Namespace) -> None:
    payload = {
        "review_kind": args.review_kind or "daily",
        "note": args.note or "",
        "session_limit": args.session_limit,
        "active_within_hours": args.active_within_hours,
        "force": bool(args.force),
    }
    data = _call("POST", "/reviews/daily-run", json=payload)
    _print_json(data)


def _set_risk_policy(args: argparse.Namespace) -> None:
    raw_value = args.value
    try:
        policy_value = json.loads(raw_value)
    except ValueError:
        lowered = raw_value.strip().lower()
        if lowered == "true":
            policy_value = True
        elif lowered == "false":
            policy_value = False
        else:
            policy_value = raw_value

    data = _call("PUT", f"/risk-policies/{args.policy_key}", json={"policy_value": policy_value})
    _print_json(data)


def _list_access_actors(_: argparse.Namespace) -> None:
    data = _call("GET", "/access/actors")
    _print_json(data)


def _set_access_actor(args: argparse.Namespace) -> None:
    payload = {"role": args.role, "description": args.description or ""}
    data = _call("PUT", f"/access/actors/{args.actor_name}", json=payload)
    _print_json(data)


def _list_access_quotas(_: argparse.Namespace) -> None:
    data = _call("GET", "/access/quotas")
    _print_json(data)


def _set_access_quota(args: argparse.Namespace) -> None:
    payload = {
        "daily_task_limit": args.daily_task_limit,
        "active_task_limit": args.active_task_limit,
    }
    data = _call("PUT", f"/access/quotas/{args.actor_name}", json=payload)
    _print_json(data)


def _list_access_quota_usage(_: argparse.Namespace) -> None:
    data = _call("GET", "/access/quota-usage")
    _print_json(data)


def _list_tools(_: argparse.Namespace) -> None:
    data = _call("GET", "/tools")
    _print_json(data)


def _set_tool(args: argparse.Namespace) -> None:
    payload = {
        "enabled": args.enabled,
        "risk_level": args.risk_level,
        "description": args.description or "",
    }
    data = _call("PUT", f"/tools/{args.tool_name}", json=payload)
    _print_json(data)


def _list_model_routes(_: argparse.Namespace) -> None:
    data = _call("GET", "/model-routes")
    _print_json(data)


def _list_model_providers(_: argparse.Namespace) -> None:
    data = _call("GET", "/model-providers")
    _print_json(data)


def _set_model_route(args: argparse.Namespace) -> None:
    payload = {
        "provider": args.provider,
        "enabled": args.enabled,
        "model_name": args.model_name,
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "description": args.description or "",
    }
    data = _call("PUT", f"/model-routes/{args.route_name}", json=payload)
    _print_json(data)


def _set_model_provider(args: argparse.Namespace) -> None:
    payload = {
        "driver": args.driver,
        "base_url": args.base_url,
        "api_key_env": args.api_key_env,
        "enabled": args.enabled,
        "description": args.description or "",
    }
    data = _call("PUT", f"/model-providers/{args.provider_name}", json=payload)
    _print_json(data)


def _list_change_requests(args: argparse.Namespace) -> None:
    params = {}
    if args.status:
        params["status"] = args.status
    if args.target_type:
        params["target_type"] = args.target_type
    if args.proposal_kind:
        params["proposal_kind"] = args.proposal_kind
    data = _call("GET", "/change-requests", params=params)
    _print_json(data)


def _show_change_request(args: argparse.Namespace) -> None:
    data = _call("GET", f"/change-requests/{args.change_request_id}")
    _print_json(data)


def _show_change_request_shadow_validation(args: argparse.Namespace) -> None:
    data = _call(
        "GET",
        f"/change-requests/{args.change_request_id}/shadow-validation",
        params={"history_limit": args.history_limit},
    )
    _print_json(data)


def _create_change_request(args: argparse.Namespace) -> None:
    payload = {
        "target_type": args.target_type,
        "target_key": args.target_key,
        "proposed_payload": json.loads(args.proposed_payload),
        "rationale": args.rationale or "",
    }
    data = _call("POST", "/change-requests", json=payload)
    _print_json(data)


def _approve_change_request(args: argparse.Namespace) -> None:
    data = _call("POST", f"/change-requests/{args.change_request_id}/approve", json={"note": args.note or ""})
    _print_json(data)


def _reject_change_request(args: argparse.Namespace) -> None:
    data = _call("POST", f"/change-requests/{args.change_request_id}/reject", json={"note": args.note or ""})
    _print_json(data)


def _apply_change_request(args: argparse.Namespace) -> None:
    data = _call("POST", f"/change-requests/{args.change_request_id}/apply", json={})
    _print_json(data)


def _preview_change_request_rollback_draft(args: argparse.Namespace) -> None:
    data = _call("GET", f"/change-requests/{args.change_request_id}/rollback-draft")
    _print_json(data)


def _create_change_request_rollback(args: argparse.Namespace) -> None:
    data = _call("POST", f"/change-requests/{args.change_request_id}/rollback", json={})
    _print_json(data)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CLI for ai-assistant API")
    subparsers = parser.add_subparsers(dest="command")

    task_parser = subparsers.add_parser("task", help="Task operations")
    task_sub = task_parser.add_subparsers(dest="subcommand")
    task_list = task_sub.add_parser("list", help="List tasks")
    task_list.set_defaults(func=_list_tasks)

    task_create = task_sub.add_parser("create", help="Create a task")
    task_create.add_argument("-i", "--input", required=True, help="Task description / prompt")
    task_create.add_argument("--session-id", type=int, help="Attach task to a session")
    task_create.set_defaults(func=_create_task)

    task_show = task_sub.add_parser("show", help="Show a task")
    task_show.add_argument("task_id", type=int, help="Task ID")
    task_show.set_defaults(func=_show_task)

    task_resume = task_sub.add_parser("resume", help="Resume a failed or paused task")
    task_resume.add_argument("task_id", type=int, help="Task ID")
    task_resume.add_argument("--from-step", type=int, help="Resume from a specific step order")
    task_resume.add_argument("--note", default="", help="Optional resume note")
    task_resume.set_defaults(func=_resume_task)

    task_interrupt = task_sub.add_parser("interrupt", help="Interrupt or pause a task")
    task_interrupt.add_argument("task_id", type=int, help="Task ID")
    task_interrupt.add_argument("--note", default="", help="Optional interrupt note")
    task_interrupt.set_defaults(func=_interrupt_task)

    steps_parser = subparsers.add_parser("steps", help="Show task steps")
    steps_parser.add_argument("task_id", type=int, help="Task ID")
    steps_parser.set_defaults(func=_show_steps)

    checkpoint_parser = subparsers.add_parser("checkpoint", help="Show task checkpoint")
    checkpoint_parser.add_argument("task_id", type=int, help="Task ID")
    checkpoint_parser.set_defaults(func=_show_checkpoint)

    runtime_parser = subparsers.add_parser("runtime", help="Show runtime metadata")
    runtime_sub = runtime_parser.add_subparsers(dest="subcommand")
    runtime_show = runtime_sub.add_parser("show", help="Show runtime metadata")
    runtime_show.set_defaults(func=_show_runtime_metadata)

    agent_runs_parser = subparsers.add_parser("agent-runs", help="Inspect Stage 5 agent run data")
    agent_runs_sub = agent_runs_parser.add_subparsers(dest="subcommand")

    agent_runs_list = agent_runs_sub.add_parser("list", help="List agent runs")
    agent_runs_list.add_argument("--task-id", type=int, help="Filter by task ID")
    agent_runs_list.add_argument("--role", help="Filter by role")
    agent_runs_list.add_argument("--status", help="Filter by status")
    agent_runs_list.set_defaults(func=_list_agent_runs)

    agent_runs_show = agent_runs_sub.add_parser("show", help="Show one agent run")
    agent_runs_show.add_argument("agent_run_id", type=int, help="Agent run ID")
    agent_runs_show.set_defaults(func=_show_agent_run)

    agent_runs_summary = agent_runs_sub.add_parser("summary", help="Show Stage 5 summary for one task")
    agent_runs_summary.add_argument("task_id", type=int, help="Task ID")
    agent_runs_summary.add_argument("--compact", action="store_true", help="Print a compact single-line status view")
    agent_runs_summary.set_defaults(func=_show_task_agent_run_summary)

    agent_runs_status = agent_runs_sub.add_parser("status", help="List compact Stage 5 triage status for tasks")
    agent_runs_status.add_argument("--session-id", type=int, help="Filter tasks by session ID")
    agent_runs_status.set_defaults(func=_list_task_stage5_status)

    agent_runs_messages = agent_runs_sub.add_parser("messages", help="List agent run messages")
    agent_runs_messages.add_argument("agent_run_id", type=int, help="Agent run ID")
    agent_runs_messages.add_argument("--limit", type=int, default=50, help="Result limit")
    agent_runs_messages.set_defaults(func=_list_agent_run_messages)

    agent_runs_artifacts = agent_runs_sub.add_parser("artifacts", help="List agent run artifacts")
    agent_runs_artifacts.add_argument("agent_run_id", type=int, help="Agent run ID")
    agent_runs_artifacts.add_argument("--limit", type=int, default=50, help="Result limit")
    agent_runs_artifacts.set_defaults(func=_list_agent_run_artifacts)

    agent_runs_bootstrap = agent_runs_sub.add_parser("bootstrap-demo", help="Create a minimal manager-only orchestration demo for a task")
    agent_runs_bootstrap.add_argument("task_id", type=int, help="Task ID")
    agent_runs_bootstrap.add_argument("--objective", default="", help="Optional objective override")
    agent_runs_bootstrap.add_argument("--specialist-count", type=int, default=2, help="How many specialist runs to seed (1-4)")
    agent_runs_bootstrap.add_argument("--no-reviewer", action="store_true", help="Skip creating the reviewer placeholder")
    agent_runs_bootstrap.add_argument("--note", default="", help="Optional bootstrap note")
    agent_runs_bootstrap.set_defaults(func=_bootstrap_task_agent_runs)

    agent_runs_execute = agent_runs_sub.add_parser("execute-demo", help="Execute readonly specialist subtasks and create draft artifacts for a task")
    agent_runs_execute.add_argument("task_id", type=int, help="Task ID")
    agent_runs_execute.add_argument("--note", default="", help="Optional execute note")
    agent_runs_execute.add_argument("--force-rerun", action="store_true", help="Force specialist rerun even if outputs already exist")
    agent_runs_execute.set_defaults(func=_execute_task_agent_runs)

    agent_runs_execute_worker = agent_runs_sub.add_parser("execute-worker-demo", help="Queue readonly specialist subtasks for worker execution")
    agent_runs_execute_worker.add_argument("task_id", type=int, help="Task ID")
    agent_runs_execute_worker.add_argument("--note", default="", help="Optional execute note")
    agent_runs_execute_worker.add_argument("--force-rerun", action="store_true", help="Force specialist rerun even if outputs already exist")
    agent_runs_execute_worker.add_argument("--subtask-type", choices=["readonly_step_digest", "readonly_source_snapshot", "readonly_task_snapshot"], default="readonly_step_digest", help="Readonly specialist subtask type")
    agent_runs_execute_worker.add_argument("--source-kind", choices=["text_file", "json_file", "directory"], help="Source kind for readonly_source_snapshot")
    agent_runs_execute_worker.add_argument("--source-path", help="Source path for readonly_source_snapshot")
    agent_runs_execute_worker.add_argument("--source-json-path", help="Optional json_extract path for readonly_source_snapshot")
    agent_runs_execute_worker.add_argument("--dir-limit", type=int, default=20, help="Directory entry limit for readonly_source_snapshot")
    agent_runs_execute_worker.set_defaults(func=_execute_task_agent_runs_via_worker)

    agent_runs_finalize = agent_runs_sub.add_parser("finalize-demo", help="Finalize a bootstrap demo into draft/review/final artifacts")
    agent_runs_finalize.add_argument("task_id", type=int, help="Task ID")
    agent_runs_finalize.add_argument("--summary", default="", help="Optional final summary override")
    agent_runs_finalize.add_argument("--note", default="", help="Optional finalize note")
    agent_runs_finalize.add_argument("--reviewer-decision", choices=["auto", "approved", "rework_required", "rejected"], default="auto", help="Reviewer decision for the demo finalize step (default: auto)")
    agent_runs_finalize.add_argument("--allow-retry", action="store_true", help="Allow rework_required to continue with specialist reruns")
    agent_runs_finalize.set_defaults(func=_finalize_task_agent_runs)

    evaluator_runs_parser = subparsers.add_parser("evaluator-runs", help="Inspect Stage 6 evaluator records")
    evaluator_runs_sub = evaluator_runs_parser.add_subparsers(dest="subcommand")

    evaluator_runs_list = evaluator_runs_sub.add_parser("list", help="List evaluator runs")
    evaluator_runs_list.add_argument("--task-id", type=int, help="Filter by task ID")
    evaluator_runs_list.add_argument("--limit", type=int, default=20, help="Result limit")
    evaluator_runs_list.set_defaults(func=_list_evaluator_runs)

    evaluator_runs_latest = evaluator_runs_sub.add_parser("latest", help="Show latest evaluator run for a task")
    evaluator_runs_latest.add_argument("task_id", type=int, help="Task ID")
    evaluator_runs_latest.add_argument("--compact", action="store_true", help="Print a compact single-line evaluator view")
    evaluator_runs_latest.set_defaults(func=_show_latest_task_evaluator)

    evaluator_runs_show = evaluator_runs_sub.add_parser("show", help="Show one evaluator run")
    evaluator_runs_show.add_argument("evaluator_run_id", type=int, help="Evaluator run ID")
    evaluator_runs_show.set_defaults(func=_show_evaluator_run)

    workflow_proposals_parser = subparsers.add_parser("workflow-proposals", help="Inspect Stage 6 workflow proposals")
    workflow_proposals_sub = workflow_proposals_parser.add_subparsers(dest="subcommand")

    workflow_proposals_list = workflow_proposals_sub.add_parser("list", help="List workflow proposals")
    workflow_proposals_list.add_argument("--task-id", type=int, help="Filter by task ID")
    workflow_proposals_list.add_argument("--action-key", help="Filter by proposal action_key")
    workflow_proposals_list.add_argument("--priority", help="Filter by proposal priority")
    workflow_proposals_list.add_argument("--limit", type=int, default=20, help="Result limit")
    workflow_proposals_list.set_defaults(func=_list_workflow_proposals)

    workflow_proposals_task = workflow_proposals_sub.add_parser("task", help="List workflow proposals for one task")
    workflow_proposals_task.add_argument("task_id", type=int, help="Task ID")
    workflow_proposals_task.add_argument("--limit", type=int, default=20, help="Result limit")
    workflow_proposals_task.set_defaults(func=_show_task_workflow_proposals)

    workflow_proposals_latest = workflow_proposals_sub.add_parser("latest", help="Show latest workflow proposal for a task")
    workflow_proposals_latest.add_argument("task_id", type=int, help="Task ID")
    workflow_proposals_latest.add_argument("--compact", action="store_true", help="Print a compact single-line proposal view")
    workflow_proposals_latest.set_defaults(func=_show_latest_task_workflow_proposal)

    workflow_proposals_show = workflow_proposals_sub.add_parser("show", help="Show one workflow proposal")
    workflow_proposals_show.add_argument("proposal_id", type=int, help="Workflow proposal ID")
    workflow_proposals_show.set_defaults(func=_show_workflow_proposal)

    workflow_proposals_shadow_status = workflow_proposals_sub.add_parser("shadow-status", help="Show proposal-scoped shadow validation status/history")
    workflow_proposals_shadow_status.add_argument("proposal_id", type=int, help="Workflow proposal ID")
    workflow_proposals_shadow_status.add_argument("--history-limit", type=int, default=10, help="How many recent shadow validation audit events to return")
    workflow_proposals_shadow_status.set_defaults(func=_show_workflow_proposal_shadow_validation)

    workflow_proposals_draft = workflow_proposals_sub.add_parser("draft", help="Preview a change request draft from one workflow proposal")
    workflow_proposals_draft.add_argument("proposal_id", type=int, help="Workflow proposal ID")
    workflow_proposals_draft.set_defaults(func=_preview_workflow_proposal_change_request_draft)

    workflow_proposals_create_change = workflow_proposals_sub.add_parser("create-change", help="Create a pending change request from one workflow proposal")
    workflow_proposals_create_change.add_argument("proposal_id", type=int, help="Workflow proposal ID")
    workflow_proposals_create_change.add_argument("target_type", choices=["risk_policy", "tool_registry", "model_route", "model_provider", "access_quota", "access_actor", "sandbox_file"])
    workflow_proposals_create_change.add_argument("target_key", help="Target key")
    workflow_proposals_create_change.add_argument(
        "proposed_payload",
        help='JSON object payload; sandbox_file also supports {"source_path":"scripts/assistant_cli.py"}, {"source_path":"scripts/assistant_cli.py","patch":"@@ -1,4 +1,5 @@\\n ..."} or the same payload plus {"acceptance":{"script_path":"scripts/stage7_sandbox_file_acceptance_probe.sh","env":{"STAGE7_EXPECT_CONTAINS":"marker"}}}',
    )
    workflow_proposals_create_change.add_argument("--rationale", default="", help="Optional bridge rationale override")
    workflow_proposals_create_change.set_defaults(func=_create_change_request_from_workflow_proposal)

    workflow_proposals_shadow_validate = workflow_proposals_sub.add_parser("shadow-validate", help="Run proposal-scoped shadow validation")
    workflow_proposals_shadow_validate.add_argument("proposal_id", type=int, help="Workflow proposal ID")
    workflow_proposals_shadow_validate.add_argument("--note", default="", help="Optional validation note")
    workflow_proposals_shadow_validate.add_argument("--shadow-user-input", default="", help="Override shadow task user_input")
    workflow_proposals_shadow_validate.add_argument("--await-completion", action="store_true", help="Wait for completion before returning")
    workflow_proposals_shadow_validate.add_argument("--timeout-seconds", type=int, default=45, help="Completion wait timeout")
    workflow_proposals_shadow_validate.add_argument("--poll-interval-seconds", type=float, default=1.0, help="Completion polling interval")
    workflow_proposals_shadow_validate.add_argument("--no-suggested-candidate", dest="use_suggested_candidate", action="store_false", help="Disable the proposal's suggested candidate overlay")
    workflow_proposals_shadow_validate.add_argument("--candidate-target-type", default="", help="Override candidate target type")
    workflow_proposals_shadow_validate.add_argument("--candidate-target-key", default="", help="Override candidate target key")
    workflow_proposals_shadow_validate.add_argument("--candidate-payload", default="", help='Override candidate payload JSON object')
    workflow_proposals_shadow_validate.set_defaults(use_suggested_candidate=True)
    workflow_proposals_shadow_validate.set_defaults(func=_shadow_validate_workflow_proposal)

    reviews_parser = subparsers.add_parser("reviews", help="Review batch operations")
    reviews_sub = reviews_parser.add_subparsers(dest="subcommand")
    reviews_daily = reviews_sub.add_parser("daily-run", help="Run batch daily reviews")
    reviews_daily.add_argument("--review-kind", default="daily", help="Review kind, default daily")
    reviews_daily.add_argument("--note", default="", help="Optional note to attach to every review")
    reviews_daily.add_argument("--session-limit", type=int, default=20, help="Max sessions to review")
    reviews_daily.add_argument("--active-within-hours", type=int, default=24, help="Only include sessions active within N hours")
    reviews_daily.add_argument("--force", action="store_true", help="Ignore same-day dedupe")
    reviews_daily.set_defaults(func=_run_daily_reviews)

    sessions_parser = subparsers.add_parser("sessions", help="Session operations")
    sessions_sub = sessions_parser.add_subparsers(dest="subcommand")

    sessions_list = sessions_sub.add_parser("list", help="List sessions")
    sessions_list.set_defaults(func=_list_sessions)

    sessions_create = sessions_sub.add_parser("create", help="Create a session")
    sessions_create.add_argument("name", help="Session name")
    sessions_create.add_argument("--description", default="", help="Optional session description")
    sessions_create.set_defaults(func=_create_session)

    sessions_show = sessions_sub.add_parser("show", help="Show a session")
    sessions_show.add_argument("session_id", type=int, help="Session ID")
    sessions_show.set_defaults(func=_show_session)

    sessions_summary = sessions_sub.add_parser("summary", help="Show a session summary")
    sessions_summary.add_argument("session_id", type=int, help="Session ID")
    sessions_summary.set_defaults(func=_show_session_summary)

    sessions_health = sessions_sub.add_parser("health", help="Show session health and next actions")
    sessions_health.add_argument("session_id", type=int, help="Session ID")
    sessions_health.set_defaults(func=_show_session_health)

    sessions_memory_add = sessions_sub.add_parser("remember", help="Add a session memory")
    sessions_memory_add.add_argument("session_id", type=int, help="Session ID")
    sessions_memory_add.add_argument("--category", required=True, help="Memory category")
    sessions_memory_add.add_argument("--content", required=True, help="Memory content")
    sessions_memory_add.add_argument("--importance", type=int, default=3, help="Memory importance (1-5)")
    sessions_memory_add.add_argument("--source-task-id", type=int, help="Optional source task ID")
    sessions_memory_add.set_defaults(func=_add_session_memory)

    sessions_memory_list = sessions_sub.add_parser("memories", help="List session memories")
    sessions_memory_list.add_argument("session_id", type=int, help="Session ID")
    sessions_memory_list.add_argument("--category", help="Filter by memory category")
    sessions_memory_list.add_argument("--limit", type=int, default=50, help="Result limit")
    sessions_memory_list.set_defaults(func=_list_session_memories)

    sessions_state_show = sessions_sub.add_parser("state", help="Show session working memory state")
    sessions_state_show.add_argument("session_id", type=int, help="Session ID")
    sessions_state_show.set_defaults(func=_show_session_state)

    sessions_state_set = sessions_sub.add_parser("state-set", help="Update session working memory state")
    sessions_state_set.add_argument("session_id", type=int, help="Session ID")
    sessions_state_set.add_argument("--summary-text", default="", help="Session summary text")
    sessions_state_set.add_argument("--preferences", help='JSON list, e.g. ["偏好简洁回答"]')
    sessions_state_set.add_argument("--open-loops", help='JSON list, e.g. ["整理 README"]')
    sessions_state_set.set_defaults(func=_set_session_state)

    sessions_state_rebuild = sessions_sub.add_parser("state-rebuild", help="Rebuild session working memory state")
    sessions_state_rebuild.add_argument("session_id", type=int, help="Session ID")
    sessions_state_rebuild.set_defaults(func=_rebuild_session_state)

    sessions_review_create = sessions_sub.add_parser("review-create", help="Create a session review")
    sessions_review_create.add_argument("session_id", type=int, help="Session ID")
    sessions_review_create.add_argument("--review-kind", default="manual", help="Review kind, e.g. manual/daily")
    sessions_review_create.add_argument("--note", default="", help="Optional review note")
    sessions_review_create.set_defaults(func=_create_session_review)

    sessions_reviews = sessions_sub.add_parser("reviews", help="List session reviews")
    sessions_reviews.add_argument("session_id", type=int, help="Session ID")
    sessions_reviews.add_argument("--limit", type=int, default=20, help="Result limit")
    sessions_reviews.set_defaults(func=_list_session_reviews)

    sessions_tasks = sessions_sub.add_parser("tasks", help="List tasks in a session")
    sessions_tasks.add_argument("session_id", type=int, help="Session ID")
    sessions_tasks.set_defaults(func=_show_session_tasks)

    approvals_parser = subparsers.add_parser("approvals", help="Approval operations")
    approvals_sub = approvals_parser.add_subparsers(dest="subcommand")
    approvals_list = approvals_sub.add_parser("list", help="List approvals")
    approvals_list.add_argument("--status", choices=("pending", "approved", "rejected"), help="Filter by status")
    approvals_list.add_argument("--task-id", type=int, help="Only list approvals for a task")
    approvals_list.set_defaults(func=_list_approvals)

    approvals_decide = approvals_sub.add_parser("decide", help="Approve or reject an approval")
    approvals_decide.add_argument("approval_id", type=int, help="Approval ID")
    approvals_decide.add_argument("--approve", action="store_true", help="Approve the request")
    approvals_decide.add_argument("--reject", action="store_true", help="Reject the request")
    approvals_decide.add_argument("--note", default="", help="Optional decision note")
    approvals_decide.set_defaults(func=_decide_approval)

    risk_parser = subparsers.add_parser("risk", help="Risk policy operations")
    risk_sub = risk_parser.add_subparsers(dest="subcommand")

    risk_list = risk_sub.add_parser("list", help="List risk policies")
    risk_list.set_defaults(func=_list_risk_policies)

    risk_set = risk_sub.add_parser("set", help="Update a risk policy")
    risk_set.add_argument("policy_key", help="Risk policy key")
    risk_set.add_argument("value", help='Policy value. Use JSON for lists, e.g. \'["GET","POST"]\'')
    risk_set.set_defaults(func=_set_risk_policy)

    actor_parser = subparsers.add_parser("actors", help="Access actor operations")
    actor_sub = actor_parser.add_subparsers(dest="subcommand")

    actor_list = actor_sub.add_parser("list", help="List access actors")
    actor_list.set_defaults(func=_list_access_actors)

    actor_set = actor_sub.add_parser("set-role", help="Create or update an access actor role")
    actor_set.add_argument("actor_name", help="Actor name")
    actor_set.add_argument("role", choices=["viewer", "operator", "admin"], help="Role to assign")
    actor_set.add_argument("--description", default="", help="Optional description")
    actor_set.set_defaults(func=_set_access_actor)

    quota_parser = subparsers.add_parser("quotas", help="Access quota operations")
    quota_sub = quota_parser.add_subparsers(dest="subcommand")

    quota_list = quota_sub.add_parser("list", help="List access quotas")
    quota_list.set_defaults(func=_list_access_quotas)

    quota_usage = quota_sub.add_parser("usage", help="Show quota usage by actor")
    quota_usage.set_defaults(func=_list_access_quota_usage)

    quota_set = quota_sub.add_parser("set", help="Update an actor quota")
    quota_set.add_argument("actor_name", help="Actor name")
    quota_set.add_argument("--daily-task-limit", type=int, required=True, help="Daily task creation limit")
    quota_set.add_argument("--active-task-limit", type=int, required=True, help="Active non-final task limit")
    quota_set.set_defaults(func=_set_access_quota)

    tools_parser = subparsers.add_parser("tools", help="Tool registry operations")
    tools_sub = tools_parser.add_subparsers(dest="subcommand")

    tools_list = tools_sub.add_parser("list", help="List registered tools")
    tools_list.set_defaults(func=_list_tools)

    tools_set = tools_sub.add_parser("set", help="Update a tool registry entry")
    tools_set.add_argument("tool_name", help="Tool name")
    tools_set.add_argument("--enabled", type=lambda value: str(value).lower() == "true", required=True, help="true or false")
    tools_set.add_argument("--risk-level", choices=["low", "medium", "high"], required=True, help="Tool risk level")
    tools_set.add_argument("--description", default="", help="Optional description")
    tools_set.set_defaults(func=_set_tool)

    models_parser = subparsers.add_parser("models", help="Model route operations")
    models_sub = models_parser.add_subparsers(dest="subcommand")

    models_list = models_sub.add_parser("list", help="List model routes")
    models_list.set_defaults(func=_list_model_routes)

    providers_list = models_sub.add_parser("providers", help="List model providers")
    providers_list.set_defaults(func=_list_model_providers)

    models_set = models_sub.add_parser("set", help="Update a model route")
    models_set.add_argument("route_name", help="Route name")
    models_set.add_argument("--provider", required=True, help="Provider name")
    models_set.add_argument("--enabled", type=lambda value: str(value).lower() == "true", required=True, help="true or false")
    models_set.add_argument("--model-name", required=True, help="Model name to route to")
    models_set.add_argument("--temperature", type=float, required=True, help="Model temperature")
    models_set.add_argument("--max-tokens", type=int, required=True, help="Max completion tokens")
    models_set.add_argument("--description", default="", help="Optional description")
    models_set.set_defaults(func=_set_model_route)

    providers_set = models_sub.add_parser("provider-set", help="Create or update a model provider")
    providers_set.add_argument("provider_name", help="Provider name")
    providers_set.add_argument("--driver", choices=["openai_compatible"], required=True, help="Provider driver")
    providers_set.add_argument("--base-url", required=True, help="Provider base URL")
    providers_set.add_argument("--api-key-env", required=True, help="Environment variable name for API key")
    providers_set.add_argument("--enabled", type=lambda value: str(value).lower() == "true", required=True, help="true or false")
    providers_set.add_argument("--description", default="", help="Optional description")
    providers_set.set_defaults(func=_set_model_provider)

    changes_parser = subparsers.add_parser("changes", help="Change request operations")
    changes_sub = changes_parser.add_subparsers(dest="subcommand")

    changes_list = changes_sub.add_parser("list", help="List change requests")
    changes_list.add_argument("--status", choices=["pending", "approved", "rejected", "applied"], help="Filter by status")
    changes_list.add_argument(
        "--target-type",
        choices=["risk_policy", "tool_registry", "model_route", "model_provider", "access_quota", "access_actor", "sandbox_file"],
        help="Filter by change target type",
    )
    changes_list.add_argument(
        "--proposal-kind",
        choices=["manual_change", "workflow_improvement", "rollback"],
        help="Filter by proposal kind",
    )
    changes_list.set_defaults(func=_list_change_requests)

    changes_show = changes_sub.add_parser("show", help="Show one change request")
    changes_show.add_argument("change_request_id", type=int, help="Change request ID")
    changes_show.set_defaults(func=_show_change_request)

    changes_shadow_status = changes_sub.add_parser("shadow-status", help="Show shadow validation status/history for one change request")
    changes_shadow_status.add_argument("change_request_id", type=int, help="Change request ID")
    changes_shadow_status.add_argument("--history-limit", type=int, default=10, help="How many recent shadow validation audit events to return")
    changes_shadow_status.set_defaults(func=_show_change_request_shadow_validation)

    changes_shadow_validate = changes_sub.add_parser("shadow-validate", help="Run shadow validation for one change request")
    changes_shadow_validate.add_argument("change_request_id", type=int, help="Change request ID")
    changes_shadow_validate.add_argument("--note", default="", help="Optional validation note")
    changes_shadow_validate.add_argument("--shadow-user-input", default="", help="Override shadow task user_input")
    changes_shadow_validate.add_argument("--await-completion", action="store_true", help="Wait for completion before returning")
    changes_shadow_validate.add_argument("--timeout-seconds", type=int, default=45, help="Completion wait timeout")
    changes_shadow_validate.add_argument("--poll-interval-seconds", type=float, default=1.0, help="Completion polling interval")
    changes_shadow_validate.set_defaults(func=_shadow_validate_change_request)

    changes_create = changes_sub.add_parser("create", help="Create a change request")
    changes_create.add_argument("target_type", choices=["risk_policy", "tool_registry", "model_route", "model_provider", "access_quota", "access_actor", "sandbox_file"])
    changes_create.add_argument("target_key", help="Target key")
    changes_create.add_argument(
        "proposed_payload",
        help='JSON object payload, e.g. \'{"policy_value":false}\' or sandbox_file source copy / source patch / acceptance payload',
    )
    changes_create.add_argument("--rationale", default="", help="Optional rationale")
    changes_create.set_defaults(func=_create_change_request)

    changes_approve = changes_sub.add_parser("approve", help="Approve a change request")
    changes_approve.add_argument("change_request_id", type=int, help="Change request ID")
    changes_approve.add_argument("--note", default="", help="Optional approval note")
    changes_approve.set_defaults(func=_approve_change_request)

    changes_reject = changes_sub.add_parser("reject", help="Reject a change request")
    changes_reject.add_argument("change_request_id", type=int, help="Change request ID")
    changes_reject.add_argument("--note", default="", help="Optional rejection note")
    changes_reject.set_defaults(func=_reject_change_request)

    changes_apply = changes_sub.add_parser("apply", help="Apply an approved change request")
    changes_apply.add_argument("change_request_id", type=int, help="Change request ID")
    changes_apply.set_defaults(func=_apply_change_request)

    changes_rollback_draft = changes_sub.add_parser("rollback-draft", help="Preview rollback draft for an applied change request")
    changes_rollback_draft.add_argument("change_request_id", type=int, help="Change request ID")
    changes_rollback_draft.set_defaults(func=_preview_change_request_rollback_draft)

    changes_rollback_create = changes_sub.add_parser("rollback-create", help="Create rollback change request for an applied change request")
    changes_rollback_create.add_argument("change_request_id", type=int, help="Change request ID")
    changes_rollback_create.set_defaults(func=_create_change_request_rollback)

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if not getattr(args, "func", None):
        parser.print_help()
        sys.exit(1)

    if getattr(args, "approve", False) and getattr(args, "reject", False):
        print("Choose either --approve or --reject", file=sys.stderr)
        sys.exit(1)
    if getattr(args, "reject", False) and not getattr(args, "approve", False):
        # mark reject for helper
        args.approve = False

    if args.command == "approvals" and args.subcommand == "decide" and not (args.approve or args.reject):
        print("Please specify --approve or --reject", file=sys.stderr)
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()

# stage7 sandbox acceptance pass 2026-03-21_061326
