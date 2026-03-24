from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def create_agent_artifact(
    cur,
    task_run_id: int,
    agent_run_id: int | None,
    artifact_type: str,
    summary: str,
    content: Any,
    version: int = 1,
    *,
    safe_json_dumps,
) -> int:
    cur.execute(
        """
        INSERT INTO agent_artifacts (task_run_id, agent_run_id, artifact_type, summary, content_json, version)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id;
        """,
        (task_run_id, agent_run_id, artifact_type, summary, safe_json_dumps(content), int(version)),
    )
    return int(cur.fetchone()["id"])


def create_agent_message(
    cur,
    task_run_id: int,
    agent_run_id: int | None,
    sender_role: str,
    recipient_role: str,
    message_type: str,
    payload: Any,
    *,
    safe_json_dumps,
) -> int:
    cur.execute(
        """
        INSERT INTO agent_messages (task_run_id, agent_run_id, sender_role, recipient_role, message_type, payload_json)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id;
        """,
        (task_run_id, agent_run_id, sender_role, recipient_role, message_type, safe_json_dumps(payload)),
    )
    return int(cur.fetchone()["id"])


def create_agent_run(
    cur,
    task_run_id: int,
    role: str,
    status: str,
    *,
    parent_agent_run_id: int | None = None,
    attempt: int = 1,
    brief_artifact_id: int | None = None,
    output_artifact_id: int | None = None,
    review_artifact_id: int | None = None,
    execution_mode: str = "",
    execution_request: Any | None = None,
    source_task_run_id: int | None = None,
    assigned_step_orders: list[int] | None = None,
    assigned_model: str = "",
    assigned_tool_profile: str = "",
    error_summary: str = "",
    started: bool = False,
    completed: bool = False,
    safe_json_dumps=None,
) -> int:
    started_at = datetime.now(timezone.utc) if started else None
    completed_at = datetime.now(timezone.utc) if completed else None
    cur.execute(
        """
        INSERT INTO agent_runs (
            task_run_id, parent_agent_run_id, role, status, attempt, brief_artifact_id,
            output_artifact_id, review_artifact_id, execution_mode, execution_request_json,
            source_task_run_id, assigned_step_orders_json, assigned_model, assigned_tool_profile,
            error_summary, created_at, updated_at, started_at, completed_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, %s, %s)
        RETURNING id;
        """,
        (
            task_run_id,
            parent_agent_run_id,
            role,
            status,
            int(attempt),
            brief_artifact_id,
            output_artifact_id,
            review_artifact_id,
            execution_mode,
            safe_json_dumps(execution_request) if execution_request is not None else None,
            source_task_run_id,
            safe_json_dumps(assigned_step_orders or []),
            assigned_model,
            assigned_tool_profile,
            error_summary,
            started_at,
            completed_at,
        ),
    )
    return int(cur.fetchone()["id"])


def create_evaluator_run(
    cur,
    *,
    task_run_id: int,
    manager_agent_run_id: int | None,
    reviewer_agent_run_id: int | None,
    final_artifact_id: int | None,
    review_artifact_id: int | None,
    decision: str,
    score: int,
    failure_reason: str,
    failure_stage: str,
    criteria: Any,
    step_stats: Any,
    workflow_proposal: Any,
    summary: str,
    recommendation: str,
    ensure_evaluator_tables,
    safe_json_dumps,
    source: str = "task_runtime_postrun_v1",
    evaluator_kind: str = "stage6_quality_gate",
    status: str = "completed",
) -> int:
    ensure_evaluator_tables(cur)
    cur.execute(
        """
        INSERT INTO evaluator_runs (
            task_run_id, manager_agent_run_id, reviewer_agent_run_id, final_artifact_id, review_artifact_id,
            evaluator_kind, status, decision, score, failure_reason, failure_stage,
            criteria_json, step_stats_json, proposal_json, summary, recommendation, source
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id;
        """,
        (
            task_run_id,
            manager_agent_run_id,
            reviewer_agent_run_id,
            final_artifact_id,
            review_artifact_id,
            evaluator_kind,
            status,
            decision,
            int(score),
            failure_reason,
            failure_stage,
            safe_json_dumps(criteria),
            safe_json_dumps(step_stats),
            safe_json_dumps(workflow_proposal),
            summary,
            recommendation,
            source,
        ),
    )
    return int(cur.fetchone()["id"])


def build_review_criteria(
    *,
    task_status: str,
    step_rows: list[dict[str, Any]],
    specialist_draft_count: int,
    reviewer_decision: str,
) -> dict[str, Any]:
    total_steps = len(step_rows)
    completed_steps = sum(1 for row in step_rows if row.get("status") == "completed")
    failed_steps = sum(1 for row in step_rows if row.get("status") == "failed")
    pending_steps = max(0, total_steps - completed_steps - failed_steps)
    criteria = [
        {
            "criterion": "specialist_drafts_present",
            "passed": specialist_draft_count > 0,
            "actual": specialist_draft_count,
        },
        {
            "criterion": "task_step_coverage_available",
            "passed": total_steps > 0 or task_status in {"completed", "failed", "waiting_approval"},
            "actual": total_steps,
        },
        {
            "criterion": "reviewer_decision_recorded",
            "passed": reviewer_decision in {"approved", "rework_required", "rejected"},
            "actual": reviewer_decision,
        },
    ]
    score = 100
    if failed_steps:
        score -= min(30, failed_steps * 10)
    if reviewer_decision == "rework_required":
        score -= 25
    elif reviewer_decision == "rejected":
        score -= 45
    if specialist_draft_count == 0:
        score -= 40
    score = max(0, min(100, score))
    return {
        "criteria": criteria,
        "score": score,
        "step_stats": {
            "total_steps": total_steps,
            "completed_steps": completed_steps,
            "failed_steps": failed_steps,
            "pending_steps": pending_steps,
        },
    }


def derive_evaluator_failure_profile(
    *,
    task_status: str,
    step_rows: list[dict[str, Any]],
    specialist_draft_count: int,
    reviewer_decision: str,
) -> dict[str, str]:
    total_steps = len(step_rows)
    completed_steps = sum(1 for row in step_rows if row.get("status") == "completed")
    failed_steps = sum(1 for row in step_rows if row.get("status") == "failed")

    if reviewer_decision == "approved":
        return {
            "failure_reason": "none",
            "failure_stage": "none",
            "recommendation": "当前质量门通过，可以继续推进主链，或把 workflow proposal 作为后续优化输入。",
            "summary": "evaluator 判定当前主链结果健康，可继续推进。",
        }
    if failed_steps > 0 or task_status == "failed":
        return {
            "failure_reason": "task_failed_step",
            "failure_stage": "execution",
            "recommendation": "优先检查 failed steps 的错误摘要，修复输入或步骤依赖后再执行。",
            "summary": "evaluator 发现主链执行阶段存在 failed step。",
        }
    if specialist_draft_count == 0:
        return {
            "failure_reason": "missing_specialist_outputs",
            "failure_stage": "specialist",
            "recommendation": "需要先补齐 specialist outputs，再让 manager/reviewer 继续收敛。",
            "summary": "evaluator 发现 specialist outputs 缺失，无法形成有效汇总。",
        }
    if total_steps > 0 and completed_steps < total_steps:
        return {
            "failure_reason": "incomplete_execution",
            "failure_stage": "execution",
            "recommendation": "补齐 pending/running steps 后重新生成 drafts 并再次评估。",
            "summary": "evaluator 发现任务执行尚未完成，结果需要返工。",
        }
    if reviewer_decision == "rejected":
        return {
            "failure_reason": "reviewer_rejected",
            "failure_stage": "review",
            "recommendation": "需要 operator 接管并重新规划，再决定是否继续拆解执行。",
            "summary": "evaluator 根据 reviewer 拒绝结果要求人工接管。",
        }
    if reviewer_decision == "rework_required":
        return {
            "failure_reason": "reviewer_requested_rework",
            "failure_stage": "review",
            "recommendation": "按 reviewer 建议返工 specialists 或重新汇总后再次评估。",
            "summary": "evaluator 根据 reviewer 返工结果要求继续补强输出。",
        }
    return {
        "failure_reason": "unknown",
        "failure_stage": "unknown",
        "recommendation": "需要人工检查当前 evaluator 输出与任务上下文。",
        "summary": "evaluator 无法归类当前失败原因。",
    }


def build_workflow_proposal(
    *,
    task_id: int,
    reviewer_decision: str,
    failure_profile: dict[str, str],
    quality_bundle: dict[str, Any],
    next_strategy: str,
) -> dict[str, Any]:
    failure_reason = str(failure_profile.get("failure_reason") or "unknown")
    failure_stage = str(failure_profile.get("failure_stage") or "unknown")
    recommendation = str(failure_profile.get("recommendation") or "").strip()
    score = int(quality_bundle.get("score") or 0)

    priority = "medium"
    target_surface = "stage5_orchestration"
    action_key = "inspect_manually"
    title = "人工检查当前闭环"
    action_payload: dict[str, Any] = {"recommended_action": "inspect_manually"}

    if failure_reason == "none":
        priority = "low"
        target_surface = "stage6_evaluator"
        action_key = "expand_specialist_scope"
        title = "扩展 specialist 子任务覆盖面"
        action_payload = {
            "recommended_action": "expand_specialist_scope",
            "candidate_subtasks": ["readonly_source_snapshot"],
            "trigger": "quality_gate_passed",
        }
    elif failure_reason == "task_failed_step":
        priority = "high"
        target_surface = "task_runtime"
        action_key = "repair_failed_steps"
        title = "修复 failed steps 后重跑主任务"
        action_payload = {
            "recommended_action": "repair_failed_steps",
            "retry_scope": "task_steps",
            "expected_next_strategy": "resume_task",
        }
    elif failure_reason == "missing_specialist_outputs":
        priority = "high"
        target_surface = "stage5_specialists"
        action_key = "queue_specialists"
        title = "补齐 specialist outputs"
        action_payload = {
            "recommended_action": "queue_specialists",
            "dispatch": "task_runtime_postrun",
            "expected_next_strategy": "generate_drafts",
        }
    elif failure_reason == "incomplete_execution":
        priority = "high"
        target_surface = "stage5_specialists"
        action_key = "rerun_incomplete_specialists"
        title = "重跑未完成 specialist"
        action_payload = {
            "recommended_action": "rerun_incomplete_specialists",
            "dispatch": "task_runtime_postrun",
            "force_rerun": True,
        }
    elif failure_reason == "reviewer_rejected":
        priority = "high"
        target_surface = "operator_escalation"
        action_key = "escalate_to_operator"
        title = "升级 operator 重新规划"
        action_payload = {
            "recommended_action": "escalate_to_operator",
            "expected_next_strategy": "replan_task",
        }
    elif failure_reason == "reviewer_requested_rework":
        priority = "medium"
        target_surface = "stage5_manager_retry"
        action_key = "rerun_specialists_then_finalize"
        title = "重跑 specialists 后再次汇总"
        action_payload = {
            "recommended_action": "rerun_specialists_then_finalize",
            "dispatch": "task_runtime_postrun",
            "followed_by": "mainline_finalize",
        }

    return {
        "version": "stage6-workflow-proposal-v1",
        "task_id": task_id,
        "status": "suggested",
        "decision": reviewer_decision,
        "score": score,
        "failure_reason": failure_reason,
        "failure_stage": failure_stage,
        "next_strategy": next_strategy,
        "priority": priority,
        "target_surface": target_surface,
        "action_key": action_key,
        "title": title,
        "rationale": recommendation,
        "action_payload": action_payload,
        "auto_apply_eligible": False,
    }


def build_runtime_feedback_context_text(latest_evaluator: dict[str, Any] | None) -> str:
    feedback = dict(latest_evaluator or {})
    if not feedback:
        return ""
    decision = str(feedback.get("decision") or "").strip()
    recommendation = str(feedback.get("recommendation") or "").strip()
    proposal = feedback.get("proposal") if isinstance(feedback.get("proposal"), dict) else {}
    proposal_action = str(proposal.get("action_key") or "").strip()
    if not any((decision, recommendation, proposal_action)):
        return ""

    lines = ["最近 evaluator 反馈："]
    if decision:
        lines.append(f"- decision: {decision}")
    if recommendation:
        lines.append(f"- recommendation: {recommendation[:280]}")
    if proposal_action:
        lines.append(f"- workflow proposal: {proposal_action}")
    return "\n".join(lines)


def augment_user_input_with_runtime_feedback(user_input: str, latest_evaluator: dict[str, Any] | None) -> str:
    feedback_text = build_runtime_feedback_context_text(latest_evaluator)
    normalized_user_input = str(user_input or "").strip()
    if not feedback_text:
        return normalized_user_input
    if not normalized_user_input:
        return feedback_text
    return f"{normalized_user_input}\n\n{feedback_text}"


def resolve_specialist_fanout_strategy(
    task_row: dict[str, Any],
    latest_evaluator: dict[str, Any] | None = None,
    *,
    extract_task_intent,
    extract_deliverable_spec,
    auto_stage5_specialist_count: int,
) -> dict[str, Any]:
    task_intent = extract_task_intent(task_row)
    deliverable_spec = extract_deliverable_spec(task_row)
    deliverable_type = str(deliverable_spec.get("deliverable_type") or "").strip()
    proposal = latest_evaluator.get("proposal") if isinstance(latest_evaluator, dict) else {}
    proposal_action = str((proposal or {}).get("action_key") or "").strip()
    evaluator_decision = str((latest_evaluator or {}).get("decision") or "").strip()
    evaluator_failure_stage = str((latest_evaluator or {}).get("failure_stage") or "").strip()
    needs_clarification = bool(task_intent.get("needs_clarification"))
    breadth_first = deliverable_type in {"research_summary", "research_then_generate_bundle", "execution_result"}
    needs_expansion = evaluator_decision in {"rework_required", "rejected"} or proposal_action == "expand_specialist_scope"

    if needs_clarification:
        return {
            "enabled": False,
            "specialist_count": 0,
            "use_restricted_probe": False,
            "reason": "clarification_pending",
        }

    specialist_count = 1
    if breadth_first:
        specialist_count = max(2, auto_stage5_specialist_count)
    if needs_expansion:
        specialist_count = min(4, max(specialist_count + 1, 2))

    enabled = breadth_first or needs_expansion
    return {
        "enabled": enabled,
        "specialist_count": specialist_count if enabled else 0,
        "use_restricted_probe": bool(enabled and needs_expansion and evaluator_failure_stage in {"execution", "review"}),
        "reason": "evaluator_feedback" if needs_expansion else ("deliverable_breadth" if breadth_first else "not_needed"),
    }


def resolve_reviewer_decision(
    *,
    task_status: str,
    step_rows: list[dict[str, Any]],
    specialist_draft_count: int,
) -> tuple[str, str]:
    total_steps = len(step_rows)
    completed_steps = sum(1 for row in step_rows if row.get("status") == "completed")
    failed_steps = sum(1 for row in step_rows if row.get("status") == "failed")

    if failed_steps > 0 or task_status == "failed":
        return "rejected", "auto"
    if specialist_draft_count == 0:
        return "rework_required", "auto"
    if total_steps > 0 and completed_steps < total_steps:
        return "rework_required", "auto"
    return "approved", "auto"


def build_specialist_step_partitions(
    *,
    step_rows: list[dict[str, Any]],
    specialist_count: int,
    task_row: dict[str, Any],
    build_task_display_input_excerpt,
    build_task_result_excerpt,
) -> tuple[list[dict[str, Any]], list[list[dict[str, Any]]], dict[str, int]]:
    step_outline = [
        {
            "step_order": int(row["step_order"]),
            "step_name": row["step_name"],
            "status": row["status"],
            "tool_name": row.get("tool_name") or "",
        }
        for row in step_rows[:6]
    ]
    partitions: list[list[dict[str, Any]]] = [[] for _ in range(max(1, specialist_count))]
    if step_rows:
        for index, step_row in enumerate(step_rows):
            partitions[index % len(partitions)].append(
                {
                    "step_order": int(step_row["step_order"]),
                    "step_name": step_row["step_name"],
                    "status": step_row["status"],
                    "tool_name": step_row.get("tool_name") or "",
                    "input_excerpt": str(step_row.get("input_payload") or "")[:180],
                    "output_excerpt": str(step_row.get("output_payload") or "")[:220],
                    "error_excerpt": str(step_row.get("error_message") or "")[:160],
                }
            )
    else:
        fallback_step = {
            "step_order": 0,
            "step_name": "task-result-fallback",
            "status": task_row.get("status") or "unknown",
            "tool_name": "",
            "input_excerpt": build_task_display_input_excerpt(task_row),
            "output_excerpt": build_task_result_excerpt(task_row),
            "error_excerpt": str(task_row.get("error_message") or "")[:160],
        }
        partitions = [[dict(fallback_step)] for _ in partitions]

    step_status_counts: dict[str, int] = {}
    for row in step_rows:
        status_key = str(row.get("status") or "unknown")
        step_status_counts[status_key] = int(step_status_counts.get(status_key, 0)) + 1
    if not step_status_counts:
        fallback_status = str(task_row.get("status") or "unknown")
        step_status_counts[fallback_status] = 1
    return step_outline, partitions, step_status_counts


def build_specialist_execution_request(
    *,
    slot: int,
    manager_objective: str,
    assigned_steps: list[dict[str, Any]] | None = None,
    brief_artifact_id: int | None = None,
    plan_artifact_id: int | None = None,
    note: str = "",
    execution_mode: str = "task_postrun_readonly_v1",
    tool_profile: str = "specialist-readonly",
    subtask_type: str = "readonly_step_digest",
    source: dict[str, Any] | None = None,
    restricted_specialist_subtask_type: str = "restricted_shell_probe",
) -> dict[str, Any]:
    assigned_steps = assigned_steps or []
    assigned_step_orders = [int(step.get("step_order") or 0) for step in assigned_steps if int(step.get("step_order") or 0) > 0]
    source = source or {}
    deliverable = f"specialist-{slot} readonly digest"
    scope = "plan_boundary_digest" if slot == 1 else "risk_result_digest"
    constraints = ["readonly-only", "do-not-write-files", "do-not-emit-final-answer"]
    success_criteria = [
        "summarize assigned steps",
        "highlight risks and gaps",
        "produce manager-consumable digest",
    ]
    if subtask_type == "readonly_task_snapshot":
        deliverable = "readonly task snapshot"
        scope = "task_snapshot"
        success_criteria = [
            "return bounded task-level status snapshot",
            "include latest execution and review signals",
            "highlight next operator or manager action",
        ]
    elif subtask_type == restricted_specialist_subtask_type:
        deliverable = "restricted shell probe"
        scope = "restricted_tool_probe"
        constraints = ["shell-whitelist-only", "no-destructive-commands", "do-not-emit-final-answer"]
        success_criteria = [
            "run a bounded restricted-tool probe",
            "summarize restricted-tool observations for manager",
            "highlight approval or execution-time risks",
        ]
    return {
        "execution_mode": execution_mode,
        "tool_profile": tool_profile,
        "subtask_type": subtask_type,
        "slot": slot,
        "objective": manager_objective,
        "scope": scope,
        "deliverable": deliverable,
        "assigned_step_orders": assigned_step_orders,
        "source": source,
        "focus_questions": [
            "这个子问题最关键的信息是什么",
            "有哪些明显缺口、风险或需要继续跟进的点",
        ],
        "evidence_refs": [
            {"artifact_id": artifact_id, "label": label}
            for artifact_id, label in [
                (brief_artifact_id, "specialist_brief"),
                (plan_artifact_id, "manager_plan"),
            ]
            if artifact_id
        ],
        "constraints": constraints,
        "success_criteria": success_criteria,
        "note": note,
    }


def is_mainline_specialist_tool_profile(
    value: Any,
    *,
    mainline_specialist_tool_profiles: set[str],
) -> bool:
    return str(value or "").strip() in mainline_specialist_tool_profiles


def is_mainline_specialist_execution_mode(
    value: Any,
    *,
    auto_stage5_execution_mode: str,
    auto_stage5_runtime_execution_mode: str,
) -> bool:
    return str(value or "").strip() in {auto_stage5_execution_mode, auto_stage5_runtime_execution_mode}


def build_restricted_specialist_source(
    *,
    task_row: dict[str, Any],
    assigned_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    restricted_tools = sorted(
        {
            str(step.get("tool_name") or "").strip()
            for step in assigned_steps
            if str(step.get("tool_name") or "").strip()
        }
    )
    command = "ls /workspace" if any(tool_name in {"file_write", "write_json"} for tool_name in restricted_tools) else "pwd"
    return {
        "command": command,
        "restricted_tools": restricted_tools,
        "task_status": str(task_row.get("status") or "unknown"),
    }


def build_mainline_specialist_specs(
    *,
    step_rows: list[dict[str, Any]],
    task_row: dict[str, Any],
    fanout_strategy: dict[str, Any] | None = None,
    auto_stage5_specialist_count: int,
    restricted_specialist_subtask_type: str,
    restricted_specialist_tool_names: set[str],
    build_task_display_input_excerpt,
    build_task_result_excerpt,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    strategy = dict(fanout_strategy or {})
    base_specialist_count = int(strategy.get("specialist_count") or auto_stage5_specialist_count)
    base_specialist_count = max(1, min(base_specialist_count, 4))
    step_outline, specialist_partitions, step_status_counts = build_specialist_step_partitions(
        step_rows=step_rows,
        specialist_count=base_specialist_count,
        task_row=task_row,
        build_task_display_input_excerpt=build_task_display_input_excerpt,
        build_task_result_excerpt=build_task_result_excerpt,
    )
    specs: list[dict[str, Any]] = []
    for index in range(base_specialist_count):
        slot = index + 1
        use_restricted_probe = bool(strategy.get("use_restricted_probe")) and slot == base_specialist_count
        subtask_type = "readonly_task_snapshot" if slot == 1 else "readonly_step_digest"
        tool_profile = "specialist-readonly"
        source = {}
        if use_restricted_probe:
            subtask_type = restricted_specialist_subtask_type
            tool_profile = "specialist-restricted"
            source = build_restricted_specialist_source(
                task_row=task_row,
                assigned_steps=specialist_partitions[index],
            )
        specs.append(
            {
                "slot": slot,
                "subtask_type": subtask_type,
                "tool_profile": tool_profile,
                "scope": "task_snapshot" if slot == 1 else "risk_result_digest",
                "assigned_steps": specialist_partitions[index],
                "source": source,
            }
        )

    restricted_assigned_steps = [
        {
            "step_order": int(step_row["step_order"]),
            "step_name": step_row["step_name"],
            "status": step_row["status"],
            "tool_name": step_row.get("tool_name") or "",
            "input_excerpt": str(step_row.get("input_payload") or "")[:180],
            "output_excerpt": str(step_row.get("output_payload") or "")[:220],
            "error_excerpt": str(step_row.get("error_message") or "")[:160],
        }
        for step_row in step_rows
        if str(step_row.get("tool_name") or "").strip() in restricted_specialist_tool_names
    ]
    if restricted_assigned_steps and len(specs) < 4 and not bool(strategy.get("use_restricted_probe")):
        specs.append(
            {
                "slot": len(specs) + 1,
                "subtask_type": restricted_specialist_subtask_type,
                "tool_profile": "specialist-restricted",
                "scope": "restricted_tool_probe",
                "assigned_steps": restricted_assigned_steps,
                "source": build_restricted_specialist_source(
                    task_row=task_row,
                    assigned_steps=restricted_assigned_steps,
                ),
            }
        )
    return step_outline, specs, step_status_counts


def build_specialist_draft_payload(
    *,
    slot: int,
    task_id: int,
    agent_run_id: int,
    manager_objective: str,
    task_row: dict[str, Any],
    step_outline: list[dict[str, Any]],
    assigned_steps: list[dict[str, Any]],
    plan_artifact_id: int | None,
    note: str,
    step_status_counts: dict[str, int],
    execution_request: dict[str, Any],
    multi_agent_protocol_version: str,
    auto_stage5_execution_mode: str,
) -> dict[str, Any]:
    execution_mode = str(execution_request.get("execution_mode") or auto_stage5_execution_mode).strip() or auto_stage5_execution_mode
    subtask_type = str(execution_request.get("subtask_type") or "readonly_step_digest").strip() or "readonly_step_digest"
    assigned_completed_steps = sum(1 for step in assigned_steps if step.get("status") == "completed")
    assigned_failed_steps = sum(1 for step in assigned_steps if step.get("status") == "failed")
    assigned_pending_steps = max(0, len(assigned_steps) - assigned_completed_steps - assigned_failed_steps)
    assigned_step_orders = [int(step.get("step_order") or 0) for step in assigned_steps if int(step.get("step_order") or 0) > 0]
    completed_names = [str(step.get("step_name") or "") for step in assigned_steps if step.get("status") == "completed"]
    failed_names = [str(step.get("step_name") or "") for step in assigned_steps if step.get("status") == "failed"]
    pending_names = [
        str(step.get("step_name") or "")
        for step in assigned_steps
        if step.get("status") not in {"completed", "failed"}
    ]
    output_digest = [
        {
            "step_order": int(step.get("step_order") or 0),
            "step_name": step.get("step_name") or "",
            "status": step.get("status") or "unknown",
            "tool_name": step.get("tool_name") or "",
            "output_excerpt": step.get("output_excerpt") or "",
        }
        for step in assigned_steps[:3]
        if step.get("output_excerpt")
    ]
    risk_digest = [
        {
            "step_order": int(step.get("step_order") or 0),
            "step_name": step.get("step_name") or "",
            "status": step.get("status") or "unknown",
            "error_excerpt": step.get("error_excerpt") or "",
        }
        for step in assigned_steps
        if step.get("status") == "failed" or step.get("error_excerpt")
    ][:3]
    observations = [
        f"step#{int(step.get('step_order') or 0)} {step.get('step_name') or ''} -> {step.get('status') or 'unknown'}"
        for step in assigned_steps[:4]
    ]
    recommended_followups: list[str] = []
    if assigned_failed_steps:
        recommended_followups.append("优先检查 failed steps 的错误摘要并决定是否重试")
    if assigned_pending_steps:
        recommended_followups.append("补齐 pending/running steps 后再重新汇总")
    if not recommended_followups:
        recommended_followups.append("基于当前已完成步骤继续汇总为 manager final candidate")
    execution_result = {
        "execution_mode": execution_mode,
        "subtask_type": subtask_type,
        "status": "completed",
        "request_snapshot": execution_request,
        "assigned_step_orders": assigned_step_orders,
        "completed_step_names": completed_names[:6],
        "failed_step_names": failed_names[:6],
        "pending_step_names": pending_names[:6],
        "observations": observations,
        "output_digest": output_digest,
        "risk_digest": risk_digest,
        "recommended_followups": recommended_followups,
    }
    return {
        "protocol_version": multi_agent_protocol_version,
        "task_id": task_id,
        "agent_run_id": agent_run_id,
        "summary": f"子问题 {slot} 基于主链执行结果生成结构化 specialist draft",
        "output": {
            "slot": slot,
            "deliverable": f"Draft for subtask {slot}",
            "objective": manager_objective,
            "task_status": task_row.get("status") or "unknown",
            "task_result_excerpt": str(task_row.get("result") or "")[:280],
            "task_error_excerpt": str(task_row.get("error_message") or "")[:200],
            "step_outline": step_outline,
            "assigned_steps": assigned_steps,
            "subtask": {
                "type": subtask_type,
                "execution_mode": execution_mode,
                "assigned_step_orders": assigned_step_orders,
            },
            "execution_request": execution_request,
            "execution_result": execution_result,
            "execution_summary": {
                "assigned_step_count": len(assigned_steps),
                "assigned_completed_steps": assigned_completed_steps,
                "assigned_failed_steps": assigned_failed_steps,
                "assigned_pending_steps": assigned_pending_steps,
                "step_status_counts": {
                    "completed": assigned_completed_steps,
                    "failed": assigned_failed_steps,
                    "other": assigned_pending_steps,
                },
            },
            "focus": "梳理计划与任务边界" if slot == 1 else "汇总执行结果与剩余风险",
        },
        "evidence_refs": [{"artifact_id": plan_artifact_id, "label": "manager_plan"}] if plan_artifact_id else [],
        "known_gaps": [] if task_row.get("status") == "completed" else [f"task 当前状态为 {task_row.get('status') or 'unknown'}"],
        "quality_signals": {
            "task_status": task_row.get("status") or "unknown",
            "global_step_status_counts": step_status_counts,
            "specialist_execution_mode": execution_mode,
            "assigned_step_count": len(assigned_steps),
        },
        "note": note,
    }


def _is_mainline_agent_row(
    row: dict[str, Any],
    *,
    mainline_specialist_tool_profiles: set[str],
    auto_stage5_execution_mode: str,
    auto_stage5_runtime_execution_mode: str,
) -> bool:
    role = str(row.get("role") or "")
    if role == "manager":
        return str(row.get("assigned_tool_profile") or "") == "manager-mainline"
    if role == "specialist":
        return is_mainline_specialist_execution_mode(
            row.get("execution_mode"),
            auto_stage5_execution_mode=auto_stage5_execution_mode,
            auto_stage5_runtime_execution_mode=auto_stage5_runtime_execution_mode,
        ) and is_mainline_specialist_tool_profile(
            row.get("assigned_tool_profile"),
            mainline_specialist_tool_profiles=mainline_specialist_tool_profiles,
        )
    if role == "reviewer":
        return (
            str(row.get("assigned_model") or "") == "review-postrun"
            and str(row.get("assigned_tool_profile") or "") == "review-readonly"
        )
    return False


def maybe_refresh_task_runtime_manager_rollup(
    cur,
    task_id: int,
    *,
    ensure_agent_tables,
    ensure_task_steps_columns,
    parse_jsonish,
    create_agent_artifact_fn,
    create_agent_message_fn,
    insert_audit_log,
    safe_json_dumps,
    multi_agent_protocol_version: str,
    auto_stage5_runtime_execution_mode: str,
) -> None:
    ensure_agent_tables(cur)
    ensure_task_steps_columns(cur)
    cur.execute(
        """
        SELECT id, status, user_input, result, error_message
        FROM task_runs
        WHERE id = %s;
        """,
        (task_id,),
    )
    task_row = cur.fetchone()
    if not task_row:
        return

    cur.execute(
        """
        SELECT id, status, assigned_tool_profile
        FROM agent_runs
        WHERE task_run_id = %s AND role = 'manager'
        ORDER BY id ASC
        LIMIT 1;
        """,
        (task_id,),
    )
    manager_row = cur.fetchone()
    if not manager_row or str(manager_row.get("assigned_tool_profile") or "") != "manager-mainline":
        return

    cur.execute(
        """
        SELECT id, status, output_artifact_id, execution_mode, execution_request_json, completed_at
        FROM agent_runs
        WHERE task_run_id = %s AND role = 'specialist'
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    specialist_rows = list(cur.fetchall())
    completed_specialists = [row for row in specialist_rows if row.get("output_artifact_id")]
    if not completed_specialists:
        return

    output_artifact_ids = [int(row["output_artifact_id"]) for row in completed_specialists if row.get("output_artifact_id")]
    cur.execute(
        """
        SELECT id, agent_run_id, artifact_type, summary, content_json, version
        FROM agent_artifacts
        WHERE id = ANY(%s)
        ORDER BY id ASC;
        """,
        (output_artifact_ids,),
    )
    artifact_rows = {int(row["agent_run_id"]): row for row in cur.fetchall()}

    cur.execute(
        """
        SELECT step_order, status
        FROM task_steps
        WHERE task_id = %s
        ORDER BY step_order ASC;
        """,
        (task_id,),
    )
    step_rows = list(cur.fetchall())
    step_status_counts: dict[str, int] = {}
    for row in step_rows:
        status_key = str(row.get("status") or "unknown")
        step_status_counts[status_key] = int(step_status_counts.get(status_key, 0)) + 1

    rollup_items: list[dict[str, Any]] = []
    for specialist_row in completed_specialists:
        execution_request = parse_jsonish(specialist_row.get("execution_request_json"), {})
        artifact_row = artifact_rows.get(int(specialist_row["id"]))
        artifact_content = parse_jsonish((artifact_row or {}).get("content_json"), {})
        rollup_items.append(
            {
                "agent_run_id": int(specialist_row["id"]),
                "status": str(specialist_row.get("status") or "unknown"),
                "execution_mode": str(specialist_row.get("execution_mode") or ""),
                "subtask_type": str(execution_request.get("subtask_type") or "readonly_step_digest"),
                "output_artifact_id": specialist_row.get("output_artifact_id"),
                "draft_version": int((artifact_row or {}).get("version") or 1),
                "draft_summary": (artifact_row or {}).get("summary") or "",
                "completed_at": specialist_row.get("completed_at").isoformat() if specialist_row.get("completed_at") else None,
                "result_summary": str((artifact_content.get("summary") if isinstance(artifact_content, dict) else "") or ""),
            }
        )

    next_action = "observe_task"
    task_status = str(task_row.get("status") or "unknown")
    if task_status == "waiting_approval":
        next_action = "await_task_approval"
    elif task_status == "running":
        next_action = "continue_task_execution"
    elif task_status in {"completed", "failed"}:
        next_action = "ready_for_postrun_finalize"

    cur.execute(
        """
        SELECT COALESCE(MAX(version), 0) AS max_version
        FROM agent_artifacts
        WHERE task_run_id = %s AND agent_run_id = %s AND artifact_type = 'draft';
        """,
        (task_id, int(manager_row["id"])),
    )
    draft_version = int((cur.fetchone() or {}).get("max_version") or 0) + 1
    draft_artifact_id = create_agent_artifact_fn(
        cur,
        task_id,
        int(manager_row["id"]),
        "draft",
        "task runtime manager rollup",
        {
            "protocol_version": multi_agent_protocol_version,
            "task_id": task_id,
            "summary": "manager 在终态前汇总 specialist drafts，形成 execution-time fan-in 视图",
            "rollup_stage": "execution_time_fanin",
            "source": auto_stage5_runtime_execution_mode,
            "task_status": task_status,
            "task_result_excerpt": str(task_row.get("result") or "")[:240],
            "task_error_excerpt": str(task_row.get("error_message") or "")[:180],
            "completed_specialist_count": len(completed_specialists),
            "total_specialist_count": len(specialist_rows),
            "specialist_outputs": rollup_items,
            "step_status_counts": step_status_counts,
            "next_action": next_action,
        },
        version=draft_version,
        safe_json_dumps=safe_json_dumps,
    )
    cur.execute(
        """
        UPDATE agent_runs
        SET output_artifact_id = %s,
            status = CASE WHEN status = 'planned' THEN 'running' ELSE status END,
            started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (draft_artifact_id, int(manager_row["id"])),
    )
    create_agent_message_fn(
        cur,
        task_id,
        int(manager_row["id"]),
        "manager",
        "reviewer",
        "progress",
        {
            "protocol_version": multi_agent_protocol_version,
            "phase": "execution_time_fanin",
            "task_status": task_status,
            "completed_specialist_count": len(completed_specialists),
            "total_specialist_count": len(specialist_rows),
            "draft_artifact_id": draft_artifact_id,
            "next_action": next_action,
        },
        safe_json_dumps=safe_json_dumps,
    )
    insert_audit_log(
        cur,
        "agent.mainline_runtime_fanin",
        "worker",
        task_id,
        {
            "task_id": task_id,
            "manager_run_id": int(manager_row["id"]),
            "draft_artifact_id": draft_artifact_id,
            "completed_specialist_count": len(completed_specialists),
            "total_specialist_count": len(specialist_rows),
            "next_action": next_action,
        },
    )


def maybe_dispatch_task_runtime_specialists(
    task_id: int,
    reason: str,
    *,
    auto_stage5_postrun_enabled: bool,
    auto_stage5_execution_mode: str,
    auto_stage5_runtime_execution_mode: str,
    multi_agent_protocol_version: str,
    mainline_specialist_tool_profiles: set[str],
    restricted_specialist_subtask_type: str,
    auto_stage5_specialist_count: int,
    restricted_specialist_tool_names: set[str],
    get_conn,
    ensure_agent_tables,
    ensure_task_steps_columns,
    ensure_audit_logs_table,
    fetch_latest_evaluator_feedback,
    resolve_specialist_fanout_strategy,
    build_task_display_input,
    build_task_display_input_excerpt,
    build_task_result_excerpt,
    build_mainline_specialist_specs_fn,
    build_specialist_execution_request_fn,
    insert_audit_log,
    safe_json_dumps,
    enqueue_agent_run,
    acquire_agent_run_claim,
    release_agent_run_claim,
    fetch_agent_run_by_id,
    process_agent_run,
    worker_id: str,
    uuid_module,
) -> None:
    if not auto_stage5_postrun_enabled:
        return

    conn = get_conn()
    cur = conn.cursor()
    queued_specialist_ids: list[int] = []
    try:
        ensure_agent_tables(cur)
        ensure_task_steps_columns(cur)
        ensure_audit_logs_table(cur)

        cur.execute(
            """
            SELECT id, status, user_input
            FROM task_runs
            WHERE id = %s;
            """,
            (task_id,),
        )
        task_row = cur.fetchone()
        if not task_row:
            return
        task_status = str(task_row.get("status") or "unknown")
        if task_status not in {"running", "waiting_approval"}:
            return

        cur.execute(
            """
            SELECT id, role, status, brief_artifact_id, output_artifact_id, execution_mode, execution_request_json,
                   source_task_run_id, assigned_step_orders_json, assigned_model, assigned_tool_profile
            FROM agent_runs
            WHERE task_run_id = %s
            ORDER BY id ASC;
            """,
            (task_id,),
        )
        agent_rows = list(cur.fetchall())
        if not agent_rows:
            return

        if any(
            not _is_mainline_agent_row(
                row,
                mainline_specialist_tool_profiles=mainline_specialist_tool_profiles,
                auto_stage5_execution_mode=auto_stage5_execution_mode,
                auto_stage5_runtime_execution_mode=auto_stage5_runtime_execution_mode,
            )
            for row in agent_rows
        ):
            return

        manager_row = next((row for row in agent_rows if str(row.get("role") or "") == "manager"), None)
        specialist_rows = [row for row in agent_rows if str(row.get("role") or "") == "specialist"]
        if not manager_row or not specialist_rows:
            return

        cur.execute(
            """
            SELECT step_order, step_name, status, tool_name, input_payload, output_payload, error_message
            FROM task_steps
            WHERE task_id = %s
            ORDER BY step_order ASC;
            """,
            (task_id,),
        )
        step_rows = list(cur.fetchall())
        if not step_rows and task_status != "waiting_approval":
            return

        latest_evaluator = fetch_latest_evaluator_feedback(cur, task_id)
        fanout_strategy = resolve_specialist_fanout_strategy(task_row, latest_evaluator)
        if not bool(fanout_strategy.get("enabled")):
            return

        manager_objective = build_task_display_input(task_row)
        _, specialist_specs, _ = build_mainline_specialist_specs_fn(
            step_rows=step_rows,
            task_row=task_row,
            fanout_strategy=fanout_strategy,
            auto_stage5_specialist_count=auto_stage5_specialist_count,
            restricted_specialist_subtask_type=restricted_specialist_subtask_type,
            restricted_specialist_tool_names=restricted_specialist_tool_names,
            build_task_display_input_excerpt=build_task_display_input_excerpt,
            build_task_result_excerpt=build_task_result_excerpt,
        )
        plan_artifact_id = manager_row.get("brief_artifact_id") or manager_row.get("output_artifact_id")

        for index, specialist_row in enumerate(specialist_rows, start=1):
            specialist_status = str(specialist_row.get("status") or "unknown")
            runtime_refresh = (
                specialist_row.get("output_artifact_id")
                and str(specialist_row.get("execution_mode") or "") == auto_stage5_runtime_execution_mode
            )
            if specialist_status in {"queued", "running"}:
                continue
            if specialist_row.get("output_artifact_id") and not runtime_refresh:
                continue
            if specialist_status == "completed" and not runtime_refresh:
                continue
            spec = specialist_specs[index - 1] if index - 1 < len(specialist_specs) else {
                "assigned_steps": [],
                "subtask_type": "readonly_step_digest",
                "tool_profile": "specialist-readonly",
                "source": {},
            }
            assigned_steps = list(spec.get("assigned_steps") or [])
            subtask_type = str(spec.get("subtask_type") or "readonly_step_digest")
            tool_profile = str(spec.get("tool_profile") or "specialist-readonly")
            source_payload = spec.get("source") or {}
            execution_request = build_specialist_execution_request_fn(
                slot=index,
                manager_objective=manager_objective,
                assigned_steps=assigned_steps,
                brief_artifact_id=specialist_row.get("brief_artifact_id"),
                plan_artifact_id=plan_artifact_id,
                note=f"task runtime execution-time fanout ({reason})",
                execution_mode=auto_stage5_runtime_execution_mode,
                tool_profile=tool_profile,
                subtask_type=subtask_type,
                source=source_payload,
                restricted_specialist_subtask_type=restricted_specialist_subtask_type,
            )
            cur.execute(
                """
                UPDATE agent_runs
                SET status = 'queued',
                    execution_mode = %s,
                    execution_request_json = %s,
                    source_task_run_id = %s,
                    assigned_step_orders_json = %s,
                    assigned_model = %s,
                    assigned_tool_profile = %s,
                    updated_at = CURRENT_TIMESTAMP,
                    completed_at = NULL,
                    error_summary = ''
                WHERE id = %s;
                """,
                (
                    auto_stage5_runtime_execution_mode,
                    safe_json_dumps(execution_request),
                    task_id,
                    safe_json_dumps(execution_request.get("assigned_step_orders") or []),
                    f"specialist-mainline-runtime-{index}",
                    tool_profile,
                    specialist_row["id"],
                ),
            )
            create_agent_message(
                cur,
                task_id,
                specialist_row["id"],
                "manager",
                "specialist",
                "handoff",
                {
                    "protocol_version": multi_agent_protocol_version,
                    "task_run_id": task_id,
                    "execution_mode": auto_stage5_runtime_execution_mode,
                    "subtask_type": subtask_type,
                    "execution_request": execution_request,
                    "reason": reason,
                    "source": "task_runtime_mainline",
                },
                safe_json_dumps=safe_json_dumps,
            )
            queued_specialist_ids.append(int(specialist_row["id"]))

        if not queued_specialist_ids:
            return

        insert_audit_log(
            cur,
            "agent.mainline_runtime_fanout",
            "worker",
            task_id,
            {
                "task_id": task_id,
                "manager_run_id": int(manager_row["id"]),
                "queued_specialist_ids": queued_specialist_ids,
                "reason": reason,
                "task_status": task_status,
                "fanout_strategy": fanout_strategy,
            },
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()

    for specialist_run_id in queued_specialist_ids:
        enqueue_agent_run(specialist_run_id)
        claim_token = f"{worker_id}:inline_agent_run:{specialist_run_id}:{uuid_module.uuid4().hex}"
        if not acquire_agent_run_claim(specialist_run_id, claim_token):
            continue
        try:
            agent_run = fetch_agent_run_by_id(specialist_run_id)
            if agent_run and str(agent_run.get("status") or "") in {"queued", "running"}:
                process_agent_run(agent_run)
        finally:
            release_agent_run_claim(specialist_run_id, claim_token)


def maybe_create_task_postrun_agent_records(
    cur,
    task_id: int,
    user_input: str,
    *,
    auto_stage5_postrun_enabled: bool,
    auto_stage5_specialist_count: int,
    auto_stage5_execution_mode: str,
    auto_stage5_runtime_execution_mode: str,
    auto_stage5_evaluator_source: str,
    multi_agent_protocol_version: str,
    mainline_specialist_tool_profiles: set[str],
    restricted_specialist_subtask_type: str,
    restricted_specialist_tool_names: set[str],
    ensure_agent_tables,
    ensure_evaluator_tables,
    ensure_task_steps_columns,
    ensure_audit_logs_table,
    build_task_display_input,
    build_task_display_input_excerpt,
    build_task_result_excerpt,
    fetch_latest_evaluator_feedback,
    resolve_specialist_fanout_strategy,
    parse_jsonish,
    safe_json_dumps,
    insert_audit_log,
    create_agent_artifact_fn,
    create_agent_message_fn,
    create_agent_run_fn,
    create_evaluator_run_fn,
    build_mainline_specialist_specs_fn,
    build_specialist_execution_request_fn,
    build_specialist_draft_payload_fn,
    resolve_reviewer_decision_fn,
    build_review_criteria_fn,
    derive_evaluator_failure_profile_fn,
    build_workflow_proposal_fn,
) -> None:
    if not auto_stage5_postrun_enabled:
        return

    ensure_agent_tables(cur)
    ensure_evaluator_tables(cur)
    ensure_task_steps_columns(cur)
    ensure_audit_logs_table(cur)

    cur.execute(
        """
        SELECT id, session_id, created_by_actor, user_input, status, result, error_message,
               runtime_overrides,
               current_step, checkpoint_path, created_at, updated_at
        FROM task_runs
        WHERE id = %s;
        """,
        (task_id,),
    )
    task_row = cur.fetchone()
    if not task_row:
        return

    cur.execute(
        """
        SELECT step_order, step_name, status, tool_name, input_payload, output_payload, error_message
        FROM task_steps
        WHERE task_id = %s
        ORDER BY step_order ASC;
        """,
        (task_id,),
    )
    step_rows = list(cur.fetchall())

    manager_objective = build_task_display_input(task_row) or str(user_input or "").strip()
    latest_evaluator = fetch_latest_evaluator_feedback(cur, task_id)
    fanout_strategy = resolve_specialist_fanout_strategy(task_row, latest_evaluator)
    if not bool(fanout_strategy.get("enabled")):
        insert_audit_log(
            cur,
            "agent.postrun_skip_strategy",
            "worker",
            task_id,
            {"task_id": task_id, "fanout_strategy": fanout_strategy},
        )
        return
    step_outline, specialist_specs, step_status_counts = build_mainline_specialist_specs_fn(
        step_rows=step_rows,
        task_row=task_row,
        fanout_strategy=fanout_strategy,
        auto_stage5_specialist_count=auto_stage5_specialist_count,
        restricted_specialist_subtask_type=restricted_specialist_subtask_type,
        restricted_specialist_tool_names=restricted_specialist_tool_names,
        build_task_display_input_excerpt=build_task_display_input_excerpt,
        build_task_result_excerpt=build_task_result_excerpt,
    )
    specialist_count = len(specialist_specs)

    cur.execute(
        """
        SELECT id, parent_agent_run_id, role, status, attempt, brief_artifact_id,
               output_artifact_id, review_artifact_id, execution_mode, execution_request_json,
               source_task_run_id, assigned_step_orders_json, assigned_model, assigned_tool_profile
        FROM agent_runs
        WHERE task_run_id = %s
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    existing_agent_rows = list(cur.fetchall())

    if existing_agent_rows and any(
        not _is_mainline_agent_row(
            row,
            mainline_specialist_tool_profiles=mainline_specialist_tool_profiles,
            auto_stage5_execution_mode=auto_stage5_execution_mode,
            auto_stage5_runtime_execution_mode=auto_stage5_runtime_execution_mode,
        )
        for row in existing_agent_rows
    ):
        insert_audit_log(
            cur,
            "agent.postrun_skip_existing",
            "worker",
            task_id,
            {"task_id": task_id, "existing_agent_run_count": len(existing_agent_rows)},
        )
        cur.connection.commit()
        return

    existing_manager_row = next((row for row in existing_agent_rows if str(row.get("role") or "") == "manager"), None)
    existing_reviewer_row = next((row for row in existing_agent_rows if str(row.get("role") or "") == "reviewer"), None)
    existing_specialist_rows = [row for row in existing_agent_rows if str(row.get("role") or "") == "specialist"]

    cur.execute(
        """
        SELECT id, agent_run_id, artifact_type, summary, content_json, version
        FROM agent_artifacts
        WHERE task_run_id = %s
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    artifact_rows = list(cur.fetchall())
    plan_artifact_row = next((row for row in artifact_rows if str(row.get("artifact_type") or "") == "plan"), None)
    final_artifact_row = next((row for row in artifact_rows if str(row.get("artifact_type") or "") == "final"), None)
    review_artifact_row = next((row for row in artifact_rows if str(row.get("artifact_type") or "") == "review"), None)
    if final_artifact_row and review_artifact_row:
        insert_audit_log(
            cur,
            "agent.postrun_skip_finalized",
            "worker",
            task_id,
            {"task_id": task_id, "manager_run_id": existing_manager_row.get("id") if existing_manager_row else None},
        )
        cur.connection.commit()
        return

    manager_plan_artifact_id = int(plan_artifact_row["id"]) if plan_artifact_row else create_agent_artifact_fn(
        cur,
        task_id,
        None,
        "plan",
        "task runtime postrun manager plan",
        {
            "protocol_version": multi_agent_protocol_version,
            "task_id": task_id,
            "objective": manager_objective,
            "task_status": task_row.get("status") or "unknown",
            "plan_source": auto_stage5_evaluator_source,
            "step_outline": step_outline,
            "step_status_counts": step_status_counts,
            "subtasks": [
                {
                    "role": "specialist",
                    "slot": int(spec.get("slot") or index + 1),
                    "scope": str(spec.get("scope") or "risk_result_digest"),
                }
                for index, spec in enumerate(specialist_specs)
            ],
        },
        safe_json_dumps=safe_json_dumps,
    )
    manager_run_id = int(existing_manager_row["id"]) if existing_manager_row else create_agent_run_fn(
        cur,
        task_id,
        "manager",
        "running",
        brief_artifact_id=manager_plan_artifact_id,
        output_artifact_id=manager_plan_artifact_id,
        assigned_model="planner-postrun",
        assigned_tool_profile="manager-mainline",
        started=True,
        safe_json_dumps=safe_json_dumps,
    )

    specialist_run_ids: list[int] = []
    specialist_draft_ids: list[int] = []
    created_message_ids: list[int] = []

    while len(existing_specialist_rows) < specialist_count:
        slot = len(existing_specialist_rows) + 1
        spec = specialist_specs[slot - 1]
        assigned_steps = list(spec.get("assigned_steps") or [])
        subtask_type = str(spec.get("subtask_type") or "readonly_step_digest")
        tool_profile = str(spec.get("tool_profile") or "specialist-readonly")
        source_payload = spec.get("source") or {}
        brief_artifact_id = create_agent_artifact_fn(
            cur,
            task_id,
            None,
            "brief",
            f"postrun specialist-{slot} brief",
            {
                "protocol_version": multi_agent_protocol_version,
                "objective": manager_objective,
                "scope": f"子问题 {slot}",
                "constraints": ["遵守当前 task scope", "不要直接给最终结论"],
                "success_criteria": [f"完成子问题 {slot} 的可交付草稿"],
                "input_refs": [{"artifact_id": manager_plan_artifact_id, "label": "manager_plan"}],
            },
            safe_json_dumps=safe_json_dumps,
        )
        execution_request = build_specialist_execution_request_fn(
            slot=slot,
            manager_objective=manager_objective,
            assigned_steps=assigned_steps,
            brief_artifact_id=brief_artifact_id,
            plan_artifact_id=manager_plan_artifact_id,
            note="task runtime postrun",
            tool_profile=tool_profile,
            subtask_type=subtask_type,
            source=source_payload,
            execution_mode=auto_stage5_execution_mode,
            restricted_specialist_subtask_type=restricted_specialist_subtask_type,
        )
        specialist_run_id = create_agent_run_fn(
            cur,
            task_id,
            "specialist",
            "planned",
            parent_agent_run_id=manager_run_id,
            brief_artifact_id=brief_artifact_id,
            execution_mode=auto_stage5_execution_mode,
            execution_request=execution_request,
            source_task_run_id=task_id,
            assigned_step_orders=execution_request.get("assigned_step_orders") or [],
            assigned_model=f"specialist-postrun-{slot}",
            assigned_tool_profile=tool_profile,
            safe_json_dumps=safe_json_dumps,
        )
        existing_specialist_rows.append(
            {
                "id": specialist_run_id,
                "role": "specialist",
                "brief_artifact_id": brief_artifact_id,
                "output_artifact_id": None,
                "execution_mode": auto_stage5_execution_mode,
                "execution_request_json": safe_json_dumps(execution_request),
                "assigned_tool_profile": tool_profile,
            }
        )
        created_message_ids.append(
            create_agent_message_fn(
                cur,
                task_id,
                specialist_run_id,
                "manager",
                "specialist",
                "brief",
                {
                    "protocol_version": multi_agent_protocol_version,
                    "task_run_id": task_id,
                    "agent_run_id": specialist_run_id,
                    "sender_role": "manager",
                    "recipient_role": "specialist",
                    "slot": slot,
                    "brief_artifact_id": brief_artifact_id,
                    "execution_request": execution_request,
                },
                safe_json_dumps=safe_json_dumps,
            )
        )

    existing_specialist_rows = existing_specialist_rows[:specialist_count]
    if not existing_reviewer_row:
        reviewer_run_id = create_agent_run_fn(
            cur,
            task_id,
            "reviewer",
            "planned",
            parent_agent_run_id=manager_run_id,
            source_task_run_id=task_id,
            assigned_model="review-postrun",
            assigned_tool_profile="review-readonly",
            safe_json_dumps=safe_json_dumps,
        )
    else:
        reviewer_run_id = int(existing_reviewer_row["id"])

    for index, specialist_row in enumerate(existing_specialist_rows, start=1):
        slot = index
        specialist_run_id = int(specialist_row["id"])
        specialist_run_ids.append(specialist_run_id)
        existing_output_artifact_id = specialist_row.get("output_artifact_id")
        specialist_execution_mode = str(specialist_row.get("execution_mode") or "")
        refresh_runtime_output = bool(existing_output_artifact_id) and specialist_execution_mode == auto_stage5_runtime_execution_mode
        if existing_output_artifact_id and not refresh_runtime_output:
            specialist_draft_ids.append(int(existing_output_artifact_id))
            continue
        spec = specialist_specs[index - 1] if index - 1 < len(specialist_specs) else {
            "assigned_steps": [],
            "tool_profile": "specialist-readonly",
            "subtask_type": "readonly_step_digest",
            "source": {},
        }
        assigned_steps = list(spec.get("assigned_steps") or [])
        brief_artifact_id = specialist_row.get("brief_artifact_id")
        execution_request = parse_jsonish(specialist_row.get("execution_request_json"), {})
        if not execution_request:
            execution_request = build_specialist_execution_request_fn(
                slot=slot,
                manager_objective=manager_objective,
                assigned_steps=assigned_steps,
                brief_artifact_id=brief_artifact_id,
                plan_artifact_id=manager_plan_artifact_id,
                note="task runtime postrun",
                tool_profile=str(spec.get("tool_profile") or "specialist-readonly"),
                subtask_type=str(spec.get("subtask_type") or "readonly_step_digest"),
                source=spec.get("source") or {},
                restricted_specialist_subtask_type=restricted_specialist_subtask_type,
                execution_mode=auto_stage5_execution_mode,
            )
        draft_version = 1
        if existing_output_artifact_id:
            cur.execute(
                """
                SELECT version
                FROM agent_artifacts
                WHERE id = %s;
                """,
                (existing_output_artifact_id,),
            )
            existing_output_row = cur.fetchone()
            draft_version = int((existing_output_row or {}).get("version") or 1) + 1
        draft_artifact_id = create_agent_artifact_fn(
            cur,
            task_id,
            specialist_run_id,
            "draft",
            f"postrun specialist-{slot} draft",
            build_specialist_draft_payload_fn(
                slot=slot,
                task_id=task_id,
                agent_run_id=specialist_run_id,
                manager_objective=manager_objective,
                task_row=task_row,
                step_outline=step_outline,
                assigned_steps=assigned_steps,
                plan_artifact_id=manager_plan_artifact_id,
                note="task runtime postrun",
                step_status_counts=step_status_counts,
                execution_request=execution_request,
                multi_agent_protocol_version=multi_agent_protocol_version,
                auto_stage5_execution_mode=auto_stage5_execution_mode,
            ),
            version=draft_version,
            safe_json_dumps=safe_json_dumps,
        )
        specialist_draft_ids.append(draft_artifact_id)
        cur.execute(
            """
            UPDATE agent_runs
            SET status = 'completed',
                output_artifact_id = %s,
                execution_mode = %s,
                execution_request_json = %s,
                source_task_run_id = %s,
                assigned_step_orders_json = %s,
                started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                completed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP,
                error_summary = ''
            WHERE id = %s;
            """,
            (
                draft_artifact_id,
                auto_stage5_execution_mode,
                safe_json_dumps(execution_request),
                task_id,
                safe_json_dumps(execution_request.get("assigned_step_orders") or []),
                specialist_run_id,
            ),
        )
        created_message_ids.append(
            create_agent_message_fn(
                cur,
                task_id,
                specialist_run_id,
                "specialist",
                "manager",
                "result",
                {
                    "protocol_version": multi_agent_protocol_version,
                    "status": "completed",
                    "artifact_ids": [draft_artifact_id],
                    "summary": f"specialist-{slot} mainline draft {'refreshed' if refresh_runtime_output else 'completed'}",
                },
                safe_json_dumps=safe_json_dumps,
            )
        )
    reviewer_decision, decision_source = resolve_reviewer_decision_fn(
        task_status=str(task_row.get("status") or "unknown"),
        step_rows=step_rows,
        specialist_draft_count=len(specialist_draft_ids),
    )
    quality_bundle = build_review_criteria_fn(
        task_status=str(task_row.get("status") or "unknown"),
        step_rows=step_rows,
        specialist_draft_count=len(specialist_draft_ids),
        reviewer_decision=reviewer_decision,
    )
    failure_profile = derive_evaluator_failure_profile_fn(
        task_status=str(task_row.get("status") or "unknown"),
        step_rows=step_rows,
        specialist_draft_count=len(specialist_draft_ids),
        reviewer_decision=reviewer_decision,
    )

    blocking_issues: list[str] = []
    follow_up_actions: list[str] = []
    reasoning_summary = "基于主链 task runtime 自动生成的 reviewer 结论"
    manager_status = "completed"
    manager_error_summary = ""
    next_strategy = "complete"
    if reviewer_decision == "rework_required":
        blocking_issues = ["reviewer 要求基于主链结果继续补强 specialist outputs"]
        follow_up_actions = ["补齐 pending/running steps", "重新汇总 final candidate"]
        manager_status = "blocked"
        manager_error_summary = "reviewer requested rework"
        next_strategy = "retry_specialists"
    elif reviewer_decision == "rejected":
        blocking_issues = ["reviewer 拒绝当前 manager final candidate"]
        follow_up_actions = ["检查 failed steps", "必要时升级人工处理"]
        manager_status = "failed"
        manager_error_summary = "reviewer rejected final candidate"
        next_strategy = "escalate_to_operator"

    review_payload = {
        "protocol_version": multi_agent_protocol_version,
        "decision": reviewer_decision,
        "reasoning_summary": reasoning_summary,
        "blocking_issues": blocking_issues,
        "follow_up_actions": follow_up_actions,
        "source_artifact_refs": specialist_draft_ids,
        "quality_criteria": quality_bundle["criteria"],
        "quality_score": quality_bundle["score"],
        "step_stats": quality_bundle["step_stats"],
        "failure_reason": failure_profile["failure_reason"],
        "failure_stage": failure_profile["failure_stage"],
        "decision_source": decision_source,
        "note": "task runtime postrun",
    }
    review_artifact_id = create_agent_artifact_fn(
        cur,
        task_id,
        reviewer_run_id,
        "review",
        "task runtime reviewer decision",
        review_payload,
        version=1,
        safe_json_dumps=safe_json_dumps,
    )
    cur.execute(
        """
        UPDATE agent_runs
        SET status = 'completed',
            review_artifact_id = %s,
            started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
            completed_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (review_artifact_id, reviewer_run_id),
    )
    created_message_ids.append(
        create_agent_message_fn(
            cur,
            task_id,
            reviewer_run_id,
            "reviewer",
            "manager",
            "review_decision",
            {
                "protocol_version": multi_agent_protocol_version,
                "decision": reviewer_decision,
                "quality_score": quality_bundle["score"],
                "failure_reason": failure_profile["failure_reason"],
                "failure_stage": failure_profile["failure_stage"],
                "decision_source": decision_source,
            },
            safe_json_dumps=safe_json_dumps,
        )
    )

    final_artifact_payload = {
        "protocol_version": multi_agent_protocol_version,
        "summary": "manager 汇总主链执行结果并生成 final artifact",
        "final_output": {
            "task_id": task_id,
            "objective": manager_objective,
            "specialist_draft_count": len(specialist_draft_ids),
            "review_status": reviewer_decision,
            "task_status": task_row.get("status") or "unknown",
            "step_count": len(step_rows),
            "next_strategy": next_strategy,
            "quality_score": quality_bundle["score"],
            "failure_reason": failure_profile["failure_reason"],
            "failure_stage": failure_profile["failure_stage"],
            "decision_source": decision_source,
            "source": auto_stage5_evaluator_source,
        },
        "source_artifact_refs": specialist_draft_ids,
        "review_status": reviewer_decision,
        "next_strategy": next_strategy,
        "quality_criteria": quality_bundle["criteria"],
        "quality_score": quality_bundle["score"],
        "step_stats": quality_bundle["step_stats"],
        "failure_reason": failure_profile["failure_reason"],
        "failure_stage": failure_profile["failure_stage"],
        "decision_source": decision_source,
    }
    final_artifact_id = create_agent_artifact_fn(
        cur,
        task_id,
        manager_run_id,
        "final",
        "task runtime manager final artifact",
        final_artifact_payload,
        version=1,
        safe_json_dumps=safe_json_dumps,
    )
    cur.execute(
        """
        UPDATE agent_runs
        SET status = %s,
            output_artifact_id = %s,
            error_summary = %s,
            started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
            completed_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (manager_status, final_artifact_id, manager_error_summary, manager_run_id),
    )
    created_message_ids.append(
        create_agent_message_fn(
            cur,
            task_id,
            manager_run_id,
            "manager",
            "operator",
            "result",
            {
                "protocol_version": multi_agent_protocol_version,
                "status": manager_status,
                "artifact_ids": [final_artifact_id],
                "summary": final_artifact_payload["summary"],
                "needs_human_review": reviewer_decision != "approved",
                "next_strategy": next_strategy,
                "quality_score": quality_bundle["score"],
                "failure_reason": failure_profile["failure_reason"],
                "failure_stage": failure_profile["failure_stage"],
                "decision_source": decision_source,
            },
            safe_json_dumps=safe_json_dumps,
        )
    )

    evaluator_summary = f"{failure_profile['summary']} score={quality_bundle['score']} decision={reviewer_decision}"
    evaluator_recommendation = failure_profile["recommendation"]
    workflow_proposal = build_workflow_proposal_fn(
        task_id=task_id,
        reviewer_decision=reviewer_decision,
        failure_profile=failure_profile,
        quality_bundle=quality_bundle,
        next_strategy=next_strategy,
    )
    evaluator_run_id = create_evaluator_run_fn(
        cur,
        task_run_id=task_id,
        manager_agent_run_id=manager_run_id,
        reviewer_agent_run_id=reviewer_run_id,
        final_artifact_id=final_artifact_id,
        review_artifact_id=review_artifact_id,
        decision=reviewer_decision,
        score=quality_bundle["score"],
        failure_reason=failure_profile["failure_reason"],
        failure_stage=failure_profile["failure_stage"],
        criteria=quality_bundle["criteria"],
        step_stats=quality_bundle["step_stats"],
        workflow_proposal=workflow_proposal,
        summary=evaluator_summary,
        recommendation=evaluator_recommendation,
        source=auto_stage5_evaluator_source,
        ensure_evaluator_tables=ensure_evaluator_tables,
        safe_json_dumps=safe_json_dumps,
    )
    insert_audit_log(
        cur,
        "agent.postrun_auto",
        "worker",
        task_id,
        {
            "task_id": task_id,
            "manager_run_id": manager_run_id,
            "specialist_run_ids": specialist_run_ids,
            "reviewer_run_id": reviewer_run_id,
            "specialist_count": specialist_count,
            "execution_mode": auto_stage5_execution_mode,
            "task_status": task_row.get("status") or "unknown",
        },
    )
    insert_audit_log(
        cur,
        "evaluator.recorded",
        "worker",
        task_id,
        {
            "task_id": task_id,
            "evaluator_run_id": evaluator_run_id,
            "manager_run_id": manager_run_id,
            "reviewer_run_id": reviewer_run_id,
            "decision": reviewer_decision,
            "score": quality_bundle["score"],
            "failure_reason": failure_profile["failure_reason"],
            "failure_stage": failure_profile["failure_stage"],
            "source": auto_stage5_evaluator_source,
            "workflow_proposal": workflow_proposal,
        },
    )
    cur.connection.commit()


def maybe_initialize_task_runtime_agent_records(
    cur,
    task_id: int,
    user_input: str,
    *,
    auto_stage5_postrun_enabled: bool,
    auto_stage5_specialist_count: int,
    auto_stage5_execution_mode: str,
    auto_stage5_runtime_execution_mode: str,
    multi_agent_protocol_version: str,
    mainline_specialist_tool_profiles: set[str],
    restricted_specialist_subtask_type: str,
    restricted_specialist_tool_names: set[str],
    ensure_agent_tables,
    ensure_evaluator_tables,
    ensure_task_steps_columns,
    ensure_audit_logs_table,
    build_task_display_input,
    build_task_display_input_excerpt,
    build_task_result_excerpt,
    safe_json_dumps,
    insert_audit_log,
    create_agent_artifact_fn,
    create_agent_message_fn,
    create_agent_run_fn,
    build_mainline_specialist_specs_fn,
    build_specialist_execution_request_fn,
) -> None:
    if not auto_stage5_postrun_enabled:
        return

    ensure_agent_tables(cur)
    ensure_evaluator_tables(cur)
    ensure_task_steps_columns(cur)
    ensure_audit_logs_table(cur)

    cur.execute(
        """
        SELECT id, role, execution_mode, assigned_model, assigned_tool_profile
        FROM agent_runs
        WHERE task_run_id = %s
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    agent_rows = list(cur.fetchall())

    if agent_rows:
        if any(
            not _is_mainline_agent_row(
                row,
                mainline_specialist_tool_profiles=mainline_specialist_tool_profiles,
                auto_stage5_execution_mode=auto_stage5_execution_mode,
                auto_stage5_runtime_execution_mode=auto_stage5_runtime_execution_mode,
            )
            for row in agent_rows
        ):
            return
        return

    cur.execute(
        """
        SELECT id, session_id, created_by_actor, user_input, status, result, error_message,
               runtime_overrides,
               current_step, checkpoint_path, created_at, updated_at
        FROM task_runs
        WHERE id = %s;
        """,
        (task_id,),
    )
    task_row = cur.fetchone()
    if not task_row:
        return

    cur.execute(
        """
        SELECT step_order, step_name, status, tool_name, input_payload, output_payload, error_message
        FROM task_steps
        WHERE task_id = %s
        ORDER BY step_order ASC;
        """,
        (task_id,),
    )
    step_rows = list(cur.fetchall())
    if not step_rows:
        return

    manager_objective = build_task_display_input(task_row) or str(user_input or "").strip()
    step_outline, specialist_specs, step_status_counts = build_mainline_specialist_specs_fn(
        step_rows=step_rows,
        task_row=task_row,
        auto_stage5_specialist_count=auto_stage5_specialist_count,
        restricted_specialist_subtask_type=restricted_specialist_subtask_type,
        restricted_specialist_tool_names=restricted_specialist_tool_names,
        build_task_display_input_excerpt=build_task_display_input_excerpt,
        build_task_result_excerpt=build_task_result_excerpt,
    )
    specialist_count = len(specialist_specs)

    plan_artifact_id = create_agent_artifact_fn(
        cur,
        task_id,
        None,
        "plan",
        "task runtime mainline manager plan",
        {
            "protocol_version": multi_agent_protocol_version,
            "task_id": task_id,
            "objective": manager_objective,
            "task_status": task_row.get("status") or "unknown",
            "plan_source": "task_runtime_init_v1",
            "step_outline": step_outline,
            "step_status_counts": step_status_counts,
            "subtasks": [
                {
                    "role": "specialist",
                    "slot": int(spec.get("slot") or index + 1),
                    "scope": str(spec.get("scope") or "risk_result_digest"),
                }
                for index, spec in enumerate(specialist_specs)
            ],
        },
        safe_json_dumps=safe_json_dumps,
    )
    manager_run_id = create_agent_run_fn(
        cur,
        task_id,
        "manager",
        "running",
        brief_artifact_id=plan_artifact_id,
        output_artifact_id=plan_artifact_id,
        assigned_model="planner-postrun",
        assigned_tool_profile="manager-mainline",
        started=True,
        safe_json_dumps=safe_json_dumps,
    )

    specialist_run_ids: list[int] = []
    for index, spec in enumerate(specialist_specs):
        slot = int(spec.get("slot") or index + 1)
        assigned_steps = list(spec.get("assigned_steps") or [])
        subtask_type = str(spec.get("subtask_type") or "readonly_step_digest")
        tool_profile = str(spec.get("tool_profile") or "specialist-readonly")
        source_payload = spec.get("source") or {}
        brief_artifact_id = create_agent_artifact_fn(
            cur,
            task_id,
            None,
            "brief",
            f"task runtime specialist-{slot} brief",
            {
                "protocol_version": multi_agent_protocol_version,
                "objective": manager_objective,
                "scope": f"子问题 {slot}",
                "constraints": ["遵守当前 task scope", "不要直接给最终结论"],
                "success_criteria": [f"完成子问题 {slot} 的可交付草稿"],
                "input_refs": [{"artifact_id": plan_artifact_id, "label": "manager_plan"}],
            },
            safe_json_dumps=safe_json_dumps,
        )
        execution_request = build_specialist_execution_request_fn(
            slot=slot,
            manager_objective=manager_objective,
            assigned_steps=assigned_steps,
            brief_artifact_id=brief_artifact_id,
            plan_artifact_id=plan_artifact_id,
            note="task runtime init",
            tool_profile=tool_profile,
            subtask_type=subtask_type,
            source=source_payload,
            execution_mode=auto_stage5_execution_mode,
            restricted_specialist_subtask_type=restricted_specialist_subtask_type,
        )
        specialist_run_id = create_agent_run_fn(
            cur,
            task_id,
            "specialist",
            "planned",
            parent_agent_run_id=manager_run_id,
            brief_artifact_id=brief_artifact_id,
            execution_mode=auto_stage5_execution_mode,
            execution_request=execution_request,
            source_task_run_id=task_id,
            assigned_step_orders=execution_request.get("assigned_step_orders") or [],
            assigned_model=f"specialist-postrun-{slot}",
            assigned_tool_profile=tool_profile,
            safe_json_dumps=safe_json_dumps,
        )
        specialist_run_ids.append(specialist_run_id)
        create_agent_message_fn(
            cur,
            task_id,
            specialist_run_id,
            "manager",
            "specialist",
            "brief",
            {
                "protocol_version": multi_agent_protocol_version,
                "task_run_id": task_id,
                "agent_run_id": specialist_run_id,
                "sender_role": "manager",
                "recipient_role": "specialist",
                "slot": slot,
                "brief_artifact_id": brief_artifact_id,
                "execution_request": execution_request,
            },
            safe_json_dumps=safe_json_dumps,
        )

    reviewer_run_id = create_agent_run_fn(
        cur,
        task_id,
        "reviewer",
        "planned",
        parent_agent_run_id=manager_run_id,
        source_task_run_id=task_id,
        assigned_model="review-postrun",
        assigned_tool_profile="review-readonly",
        safe_json_dumps=safe_json_dumps,
    )
    insert_audit_log(
        cur,
        "agent.postrun_initialized",
        "worker",
        task_id,
        {
            "task_id": task_id,
            "manager_run_id": manager_run_id,
            "specialist_run_ids": specialist_run_ids,
            "reviewer_run_id": reviewer_run_id,
            "specialist_count": specialist_count,
            "execution_mode": auto_stage5_execution_mode,
        },
    )
    cur.connection.commit()
