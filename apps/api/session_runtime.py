from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from change_request_helpers import (
    CHANGE_GATE_REQUIRED_TARGET_TYPES,
    DEFAULT_ENFORCED_CHANGE_TARGET_TYPES,
)
from core.task_runtime import (
    build_task_display_user_input,
    build_task_fact_memory_content,
    build_task_summary_memory_content,
)
from json_utils import safe_json_dumps
from serializers import serialize_session_state_row


ACTIVE_SESSION_TASK_STATUSES = {"pending", "running", "waiting_approval", "paused", "interrupt_requested"}
SUPPORTED_CHANGE_TARGET_TYPES = {
    "risk_policy",
    "tool_registry",
    "model_route",
    "model_provider",
    "access_quota",
    "access_actor",
    "sandbox_file",
}


def _parse_maybe_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


def normalize_memory_key(category: Any, content: Any) -> tuple[str, str]:
    normalized_category = str(category or "").strip().lower()
    normalized_content = " ".join(str(content or "").strip().lower().split())
    return normalized_category, normalized_content


def compute_session_health(
    task_rows: list[dict[str, Any]],
    memory_rows: list[dict[str, Any]],
    session_state_row: dict[str, Any] | None,
    review_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    active_task_count = 0
    latest_task_updated_at = None
    for row in task_rows:
        status = str(row.get("status") or "").strip()
        updated_at = row.get("updated_at")
        if status in ACTIVE_SESSION_TASK_STATUSES:
            active_task_count += 1
        if updated_at and (latest_task_updated_at is None or updated_at > latest_task_updated_at):
            latest_task_updated_at = updated_at

    duplicate_memory_count = 0
    high_importance_memory_count = 0
    seen_memory_keys: set[tuple[str, str]] = set()
    for row in memory_rows:
        importance = int(row.get("importance") or 0)
        if importance >= 4:
            high_importance_memory_count += 1
        memory_key = normalize_memory_key(row.get("category"), row.get("content"))
        if memory_key[1]:
            if memory_key in seen_memory_keys:
                duplicate_memory_count += 1
            else:
                seen_memory_keys.add(memory_key)

    state = serialize_session_state_row(session_state_row) if session_state_row else {
        "summary_text": "",
        "preferences": [],
        "open_loops": [],
        "updated_at": None,
    }
    preferences = [str(item).strip() for item in state.get("preferences", []) if str(item).strip()]
    open_loops = [str(item).strip() for item in state.get("open_loops", []) if str(item).strip()]
    state_updated_at = state.get("updated_at")
    state_is_stale = bool(latest_task_updated_at and (not state_updated_at or latest_task_updated_at > state_updated_at))

    total_reviews = len(review_rows)
    latest_review_at = review_rows[0].get("created_at") if review_rows else None
    daily_review_today = any(
        str(row.get("review_kind") or "").strip() == "daily"
        and row.get("created_at")
        and row["created_at"].date() == datetime.now(timezone.utc).date()
        for row in review_rows
    )
    needs_review = bool(active_task_count > 0 and not daily_review_today)

    recommended_actions: list[dict[str, str]] = []
    if not session_state_row:
        recommended_actions.append({"action": "rebuild_state", "reason": "session 还没有 working memory state"})
    elif state_is_stale:
        recommended_actions.append({"action": "rebuild_state", "reason": "session state 落后于最近任务更新时间"})
    if total_reviews == 0:
        recommended_actions.append({"action": "create_review", "reason": "session 还没有任何 review"})
    elif needs_review:
        recommended_actions.append({"action": "run_daily_review", "reason": "session 仍有活跃任务且今天还没有 daily review"})
    if duplicate_memory_count > 0:
        recommended_actions.append({"action": "dedupe_memories", "reason": "存在重复 memory，可先做去重再进入更深阶段"})
    if open_loops and active_task_count == 0:
        recommended_actions.append({"action": "review_open_loops", "reason": "当前没有活跃任务，但还保留 open loops 需要整理"})

    return {
        "active_task_count": active_task_count,
        "high_importance_memory_count": high_importance_memory_count,
        "duplicate_memory_count": duplicate_memory_count,
        "preference_count": len(preferences),
        "open_loop_count": len(open_loops),
        "total_reviews": total_reviews,
        "latest_review_at": latest_review_at,
        "daily_review_today": daily_review_today,
        "needs_review": needs_review,
        "state_is_stale": state_is_stale,
        "recommended_actions": recommended_actions,
    }


def compute_stage_readiness_metrics(
    total_sessions: int,
    total_session_states: int,
    total_session_reviews: int,
    active_session_count: int,
    sessions_missing_state_count: int,
    sessions_missing_review_count: int,
    sessions_needing_review_count: int,
    sessions_with_duplicate_memories_count: int,
    sessions_with_open_loops_count: int,
    access_actor_count: int,
    access_quota_count: int,
    quota_pressure_count: int,
    change_request_total_count: int,
    change_request_pending_count: int,
    change_request_approved_count: int,
    change_request_rejected_count: int,
    change_request_applied_count: int,
    stage5_mainline_task_count: int,
    stage5_runtime_fanout_task_count: int,
    stage5_role_skeleton_ready_count: int,
    stage5_terminal_mainline_task_count: int,
    stage5_terminal_ready_count: int,
    stage6_mainline_evaluator_run_count: int,
    stage6_mainline_workflow_proposal_count: int,
    stage6_auto_mapped_proposal_count: int,
    stage6_mainline_bridged_change_request_count: int,
    stage5_non_readonly_specialist_task_count: int,
    stage5_runtime_fanout_event_count: int,
    stage5_runtime_fanin_event_count: int,
    stage5_runtime_execute_event_count: int,
    stage6_failure_taxonomy_count: int,
    stage6_shadow_validation_count: int,
    stage7_workflow_improvement_change_request_count: int,
    stage7_shadow_required_change_request_count: int,
    stage7_shadow_completed_change_request_count: int,
    stage7_candidate_overlay_validation_count: int,
    stage7_candidate_match_change_request_count: int,
    stage7_patch_artifact_ready_count: int,
    stage7_rollback_ready_count: int,
    stage7_rollback_change_request_count: int,
    stage7_rollback_applied_count: int,
    stage7_sandbox_file_applied_count: int,
    stage7_sandbox_source_copy_applied_count: int,
    stage7_sandbox_source_patch_applied_count: int,
    stage7_sandbox_acceptance_passed_count: int,
    stage7_sandbox_acceptance_failed_count: int,
    stage7_sandbox_auto_rollback_applied_count: int,
) -> dict[str, Any]:
    def build_completion_progress(gates: list[tuple[str, bool]]) -> dict[str, Any]:
        met = [name for name, is_met in gates if is_met]
        missing = [name for name, is_met in gates if not is_met]
        completion_ratio = round(len(met) / len(gates), 3) if gates else 1.0
        return {
            "completion_ratio": completion_ratio,
            "completed": not missing,
            "met_completion_gates": met,
            "missing_completion_gates": missing,
        }

    total_sessions = max(total_sessions, 0)
    supported_change_target_count = len(SUPPORTED_CHANGE_TARGET_TYPES)
    required_change_gate_target_count = len(CHANGE_GATE_REQUIRED_TARGET_TYPES)
    enforced_change_target_count = len(DEFAULT_ENFORCED_CHANGE_TARGET_TYPES & CHANGE_GATE_REQUIRED_TARGET_TYPES)
    missing_change_gate_targets = sorted(CHANGE_GATE_REQUIRED_TARGET_TYPES - DEFAULT_ENFORCED_CHANGE_TARGET_TYPES)
    active_session_baseline = active_session_count or total_sessions
    stage3_ready_session_count = max(
        0,
        active_session_baseline - sessions_missing_state_count - sessions_missing_review_count - sessions_with_duplicate_memories_count,
    )
    stage3_readiness_ratio = round(stage3_ready_session_count / active_session_baseline, 3) if active_session_baseline else 1.0
    stage4_governance_ratio = round(
        enforced_change_target_count / required_change_gate_target_count,
        3,
    ) if required_change_gate_target_count else 1.0
    change_request_closed_count = change_request_rejected_count + change_request_applied_count
    change_request_closure_ratio = round(change_request_closed_count / change_request_total_count, 3) if change_request_total_count else 0.0
    change_request_apply_ratio = round(change_request_applied_count / change_request_total_count, 3) if change_request_total_count else 0.0
    actor_quota_alignment_ok = access_actor_count == access_quota_count
    stage5_runtime_fanout_ratio = (
        round(stage5_runtime_fanout_task_count / stage5_mainline_task_count, 3)
        if stage5_mainline_task_count
        else 0.0
    )
    stage5_role_skeleton_ratio = (
        round(stage5_role_skeleton_ready_count / stage5_mainline_task_count, 3)
        if stage5_mainline_task_count
        else 0.0
    )
    stage5_terminal_readiness_ratio = (
        round(stage5_terminal_ready_count / stage5_terminal_mainline_task_count, 3)
        if stage5_terminal_mainline_task_count
        else 0.0
    )
    stage6_workflow_proposal_coverage_ratio = (
        round(stage6_mainline_workflow_proposal_count / stage6_mainline_evaluator_run_count, 3)
        if stage6_mainline_evaluator_run_count
        else 0.0
    )
    stage6_bridge_activation_ratio = (
        round(stage6_mainline_bridged_change_request_count / stage6_auto_mapped_proposal_count, 3)
        if stage6_auto_mapped_proposal_count
        else 0.0
    )
    stage7_shadow_completion_ratio = (
        round(stage7_shadow_completed_change_request_count / stage7_shadow_required_change_request_count, 3)
        if stage7_shadow_required_change_request_count
        else 0.0
    )
    stage5_completion_progress = build_completion_progress([
        ("mainline_runtime_postrun", stage5_terminal_mainline_task_count > 0 and stage5_terminal_ready_count > 0),
        (
            "runtime_fanout_audited",
            stage5_runtime_fanout_event_count > 0
            and stage5_runtime_execute_event_count > 0,
        ),
        ("manager_fanin_audited", stage5_runtime_fanin_event_count > 0),
        ("reviewer_lane_ready", stage5_role_skeleton_ready_count == stage5_mainline_task_count and stage5_mainline_task_count > 0),
        ("restricted_tool_specialist_ready", stage5_non_readonly_specialist_task_count > 0),
    ])
    stage6_completion_progress = build_completion_progress([
        ("mainline_evaluator_ready", stage6_mainline_evaluator_run_count > 0),
        ("failure_taxonomy_ready", stage6_failure_taxonomy_count > 0),
        (
            "workflow_proposal_ready",
            stage6_mainline_workflow_proposal_count == stage6_mainline_evaluator_run_count
            and stage6_mainline_workflow_proposal_count > 0,
        ),
        ("change_request_bridge_ready", stage6_mainline_bridged_change_request_count > 0),
        ("shadow_validation_ready", stage6_shadow_validation_count > 0),
    ])
    stage7_groundwork_progress = build_completion_progress([
        ("patch_artifact_ready", stage7_patch_artifact_ready_count > 0),
        ("workflow_shadow_gate_ready", stage7_shadow_completed_change_request_count > 0),
        ("candidate_overlay_runtime_override_ready", stage7_candidate_overlay_validation_count > 0),
        ("payload_hash_precision_gate_ready", stage7_candidate_match_change_request_count > 0),
        ("rollback_artifact_ready", stage7_rollback_ready_count > 0),
        ("rollback_apply_ready", stage7_rollback_applied_count > 0),
    ])
    stage7_overall_progress = build_completion_progress([
        ("groundwork_completed", stage7_groundwork_progress["completed"]),
        ("sandbox_file_apply_ready", stage7_sandbox_file_applied_count > 0),
        ("sandbox_file_source_copy_ready", stage7_sandbox_source_copy_applied_count > 0),
        ("sandbox_file_source_patch_ready", stage7_sandbox_source_patch_applied_count > 0),
        (
            "sandbox_file_acceptance_ready",
            stage7_sandbox_acceptance_passed_count > 0 and stage7_sandbox_acceptance_failed_count > 0,
        ),
        ("sandbox_file_auto_rollback_ready", stage7_sandbox_auto_rollback_applied_count > 0),
    ])
    stage3_operational = (
        sessions_missing_state_count == 0
        and sessions_missing_review_count == 0
        and sessions_with_duplicate_memories_count == 0
    )
    stage4_operational = (
        not missing_change_gate_targets
        and change_request_applied_count >= 1
        and actor_quota_alignment_ok
        and access_actor_count > 0
        and access_quota_count > 0
    )
    stage5_operational = (
        stage5_mainline_task_count > 0
        and stage5_runtime_fanout_event_count > 0
        and stage5_runtime_execute_event_count > 0
        and stage5_runtime_fanin_event_count > 0
        and stage5_role_skeleton_ready_count == stage5_mainline_task_count
        and stage5_terminal_ready_count > 0
    )
    stage6_operational = (
        stage6_mainline_evaluator_run_count > 0
        and stage6_mainline_workflow_proposal_count == stage6_mainline_evaluator_run_count
        and stage6_auto_mapped_proposal_count > 0
        and stage6_mainline_bridged_change_request_count > 0
    )
    stage7_groundwork_active = any((
        stage7_workflow_improvement_change_request_count > 0,
        stage7_patch_artifact_ready_count > 0,
        stage7_rollback_change_request_count > 0,
    ))
    stage7_operational = bool(stage7_groundwork_progress["completed"])

    return {
        "stage3": {
            "total_sessions": total_sessions,
            "active_sessions": active_session_count,
            "sessions_with_state": total_session_states,
            "sessions_with_review": total_session_reviews,
            "sessions_missing_state": sessions_missing_state_count,
            "sessions_missing_review": sessions_missing_review_count,
            "sessions_needing_review": sessions_needing_review_count,
            "sessions_with_duplicate_memories": sessions_with_duplicate_memories_count,
            "sessions_with_open_loops": sessions_with_open_loops_count,
            "ready_session_count": stage3_ready_session_count,
            "readiness_ratio": stage3_readiness_ratio,
            "operational": stage3_operational,
        },
        "stage4": {
            "supported_change_target_count": supported_change_target_count,
            "change_gate_required_target_count": required_change_gate_target_count,
            "enforced_change_target_count": enforced_change_target_count,
            "change_gate_coverage_ratio": stage4_governance_ratio,
            "change_gate_missing_target_types": missing_change_gate_targets,
            "access_actor_count": access_actor_count,
            "access_quota_count": access_quota_count,
            "quota_pressure_count": quota_pressure_count,
            "actor_quota_alignment_ok": actor_quota_alignment_ok,
            "change_request_total_count": change_request_total_count,
            "change_request_pending_count": change_request_pending_count,
            "change_request_approved_count": change_request_approved_count,
            "change_request_rejected_count": change_request_rejected_count,
            "change_request_applied_count": change_request_applied_count,
            "change_request_closed_count": change_request_closed_count,
            "change_request_closure_ratio": change_request_closure_ratio,
            "change_request_apply_ratio": change_request_apply_ratio,
            "operational": stage4_operational,
            "pending_changes_require_attention": change_request_pending_count > 0,
        },
        "stage5": {
            "mainline_task_count": stage5_mainline_task_count,
            "runtime_fanout_task_count": stage5_runtime_fanout_task_count,
            "role_skeleton_ready_count": stage5_role_skeleton_ready_count,
            "runtime_fanout_ratio": stage5_runtime_fanout_ratio,
            "role_skeleton_ratio": stage5_role_skeleton_ratio,
            "terminal_mainline_task_count": stage5_terminal_mainline_task_count,
            "terminal_ready_count": stage5_terminal_ready_count,
            "terminal_readiness_ratio": stage5_terminal_readiness_ratio,
            "tasks_missing_runtime_fanout": max(0, stage5_mainline_task_count - stage5_runtime_fanout_task_count),
            "tasks_missing_role_skeleton": max(0, stage5_mainline_task_count - stage5_role_skeleton_ready_count),
            "terminal_tasks_missing_postrun": max(0, stage5_terminal_mainline_task_count - stage5_terminal_ready_count),
            "non_readonly_specialist_task_count": stage5_non_readonly_specialist_task_count,
            "runtime_fanout_event_count": stage5_runtime_fanout_event_count,
            "runtime_fanin_event_count": stage5_runtime_fanin_event_count,
            "runtime_execute_event_count": stage5_runtime_execute_event_count,
            "completion_ratio": stage5_completion_progress["completion_ratio"],
            "completed": stage5_completion_progress["completed"],
            "met_completion_gates": stage5_completion_progress["met_completion_gates"],
            "missing_completion_gates": stage5_completion_progress["missing_completion_gates"],
            "operational": stage5_operational,
        },
        "stage6": {
            "mainline_evaluator_run_count": stage6_mainline_evaluator_run_count,
            "mainline_workflow_proposal_count": stage6_mainline_workflow_proposal_count,
            "workflow_proposal_coverage_ratio": stage6_workflow_proposal_coverage_ratio,
            "auto_mapped_proposal_count": stage6_auto_mapped_proposal_count,
            "mainline_bridged_change_request_count": stage6_mainline_bridged_change_request_count,
            "bridge_activation_ratio": stage6_bridge_activation_ratio,
            "failure_taxonomy_count": stage6_failure_taxonomy_count,
            "shadow_validation_count": stage6_shadow_validation_count,
            "completion_ratio": stage6_completion_progress["completion_ratio"],
            "completed": stage6_completion_progress["completed"],
            "met_completion_gates": stage6_completion_progress["met_completion_gates"],
            "missing_completion_gates": stage6_completion_progress["missing_completion_gates"],
            "operational": stage6_operational,
        },
        "stage7": {
            "groundwork_active": stage7_groundwork_active,
            "overall_completed": stage7_overall_progress["completed"],
            "workflow_improvement_change_request_count": stage7_workflow_improvement_change_request_count,
            "shadow_required_change_request_count": stage7_shadow_required_change_request_count,
            "shadow_completed_change_request_count": stage7_shadow_completed_change_request_count,
            "shadow_pending_change_request_count": max(
                0,
                stage7_shadow_required_change_request_count - stage7_shadow_completed_change_request_count,
            ),
            "shadow_completion_ratio": stage7_shadow_completion_ratio,
            "candidate_overlay_validation_count": stage7_candidate_overlay_validation_count,
            "candidate_match_change_request_count": stage7_candidate_match_change_request_count,
            "patch_artifact_ready_count": stage7_patch_artifact_ready_count,
            "rollback_ready_count": stage7_rollback_ready_count,
            "rollback_change_request_count": stage7_rollback_change_request_count,
            "rollback_applied_count": stage7_rollback_applied_count,
            "sandbox_file_applied_count": stage7_sandbox_file_applied_count,
            "sandbox_source_copy_applied_count": stage7_sandbox_source_copy_applied_count,
            "sandbox_source_patch_applied_count": stage7_sandbox_source_patch_applied_count,
            "sandbox_acceptance_passed_count": stage7_sandbox_acceptance_passed_count,
            "sandbox_acceptance_failed_count": stage7_sandbox_acceptance_failed_count,
            "sandbox_auto_rollback_applied_count": stage7_sandbox_auto_rollback_applied_count,
            "groundwork_ratio": stage7_groundwork_progress["completion_ratio"],
            "groundwork_completed": stage7_groundwork_progress["completed"],
            "met_groundwork_gates": stage7_groundwork_progress["met_completion_gates"],
            "missing_groundwork_gates": stage7_groundwork_progress["missing_completion_gates"],
            "completion_ratio": stage7_overall_progress["completion_ratio"],
            "met_completion_gates": stage7_overall_progress["met_completion_gates"],
            "missing_completion_gates": stage7_overall_progress["missing_completion_gates"],
            "operational": stage7_operational,
            "completed": stage7_overall_progress["completed"],
        },
    }


def compute_session_state_from_rows(
    session_row: dict[str, Any],
    task_rows: list[dict[str, Any]],
    memory_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    tasks_by_status: dict[str, int] = {}
    for row in task_rows:
        status = str(row.get("status") or "unknown")
        tasks_by_status[status] = tasks_by_status.get(status, 0) + 1

    preferences: list[str] = []
    open_loops: list[str] = []
    seen_preferences: set[str] = set()
    seen_open_loops: set[str] = set()

    for row in memory_rows:
        category = str(row.get("category") or "").strip().lower()
        content = str(row.get("content") or "").strip()
        if not content:
            continue
        if category == "preference" and content not in seen_preferences:
            seen_preferences.add(content)
            preferences.append(content)
        if category in {"open_loop", "todo", "follow_up"} and content not in seen_open_loops:
            seen_open_loops.add(content)
            open_loops.append(content)

    for row in task_rows:
        status = str(row.get("status") or "")
        user_input = build_task_display_user_input(
            str(row.get("user_input") or ""),
            _parse_maybe_json(row.get("runtime_overrides")) or {},
        ).strip()
        if status in ACTIVE_SESSION_TASK_STATUSES and user_input and user_input not in seen_open_loops:
            seen_open_loops.add(user_input)
            open_loops.append(user_input)

    summary_parts = [
        f"Session: {session_row.get('name') or session_row.get('id')}",
        f"tasks={len(task_rows)}",
    ]
    if tasks_by_status:
        summary_parts.append(
            "statuses=" + ", ".join(f"{key}:{value}" for key, value in sorted(tasks_by_status.items()))
        )
    if preferences:
        summary_parts.append(f"preferences={len(preferences)}")
    if open_loops:
        summary_parts.append(f"open_loops={len(open_loops)}")

    return {
        "summary_text": " | ".join(summary_parts),
        "preferences": preferences,
        "open_loops": open_loops,
    }


def build_session_review(
    session_row: dict[str, Any],
    task_rows: list[dict[str, Any]],
    memory_rows: list[dict[str, Any]],
    session_state_row: dict[str, Any] | None,
    note: str = "",
) -> dict[str, Any]:
    tasks_by_status: dict[str, int] = {}
    for row in task_rows:
        status = str(row.get("status") or "unknown")
        tasks_by_status[status] = tasks_by_status.get(status, 0) + 1

    memory_counts: dict[str, int] = {}
    for row in memory_rows:
        category = str(row.get("category") or "unknown")
        memory_counts[category] = memory_counts.get(category, 0) + 1

    state = serialize_session_state_row(session_state_row) if session_state_row else {
        "summary_text": "",
        "preferences": [],
        "open_loops": [],
    }
    recent_completed = [
        build_task_display_user_input(
            str(row.get("user_input") or ""),
            _parse_maybe_json(row.get("runtime_overrides")) or {},
        ).strip()
        for row in task_rows
        if str(row.get("status") or "") == "completed" and str(row.get("user_input") or "").strip()
    ][:3]

    highlights: list[str] = []
    highlights.append(f"任务总数 {len(task_rows)}，状态分布：{', '.join(f'{k}:{v}' for k, v in sorted(tasks_by_status.items())) or '无'}")
    if memory_counts:
        highlights.append("记忆分类：" + ", ".join(f"{k}:{v}" for k, v in sorted(memory_counts.items())))
    preferences = [str(item).strip() for item in state.get("preferences", []) if str(item).strip()]
    if preferences:
        highlights.append("当前偏好：" + "；".join(preferences[:3]))
    if recent_completed:
        highlights.append("最近完成：" + "；".join(recent_completed))
    if note.strip():
        highlights.append("备注：" + note.strip())

    open_loops = [str(item).strip() for item in state.get("open_loops", []) if str(item).strip()]
    summary_parts = [
        f"Session Review: {session_row.get('name') or session_row.get('id')}",
        f"tasks={len(task_rows)}",
        f"memories={len(memory_rows)}",
    ]
    if preferences:
        summary_parts.append(f"preferences={len(preferences)}")
    if open_loops:
        summary_parts.append(f"open_loops={len(open_loops)}")

    return {
        "summary_text": " | ".join(summary_parts),
        "highlights": highlights,
        "open_loops": open_loops[:10],
    }


def load_session_review_context(cur, session_id: int) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    cur.execute(
        """
        SELECT id, name, description, created_at, updated_at
        FROM sessions
        WHERE id = %s;
        """,
        (session_id,),
    )
    session_row = cur.fetchone()
    if not session_row:
        raise HTTPException(status_code=404, detail="Session not found")

    cur.execute(
        """
        SELECT id, session_id, user_input, status, result, updated_at, runtime_overrides
        FROM task_runs
        WHERE session_id = %s
        ORDER BY updated_at DESC, id DESC;
        """,
        (session_id,),
    )
    task_rows = list(cur.fetchall())
    cur.execute(
        """
        SELECT id, session_id, category, content, importance, source_task_id, created_at, updated_at
        FROM session_memories
        WHERE session_id = %s
        ORDER BY importance DESC, id DESC;
        """,
        (session_id,),
    )
    memory_rows = list(cur.fetchall())
    cur.execute(
        """
        SELECT session_id, summary_text, preferences, open_loops, created_at, updated_at
        FROM session_states
        WHERE session_id = %s;
        """,
        (session_id,),
    )
    session_state_row = cur.fetchone()
    return session_row, task_rows, memory_rows, session_state_row


def upsert_computed_session_state(cur, session_id: int, computed_state: dict[str, Any]) -> dict[str, Any]:
    cur.execute(
        """
        INSERT INTO session_states (session_id, summary_text, preferences, open_loops)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (session_id) DO UPDATE
        SET summary_text = EXCLUDED.summary_text,
            preferences = EXCLUDED.preferences,
            open_loops = EXCLUDED.open_loops,
            updated_at = CURRENT_TIMESTAMP
        RETURNING session_id, summary_text, preferences, open_loops, created_at, updated_at;
        """,
        (
            session_id,
            computed_state["summary_text"],
            safe_json_dumps(computed_state["preferences"]),
            safe_json_dumps(computed_state["open_loops"]),
        ),
    )
    return serialize_session_state_row(cur.fetchone())


def refresh_session_review_context(
    cur,
    session_id: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    session_row, task_rows, _memory_rows, _session_state_row = load_session_review_context(cur, session_id)
    refresh_session_task_summary_memories(cur, task_rows)
    cur.execute(
        """
        SELECT id, session_id, category, content, importance, source_task_id, created_at, updated_at
        FROM session_memories
        WHERE session_id = %s
        ORDER BY importance DESC, id DESC;
        """,
        (session_id,),
    )
    memory_rows = list(cur.fetchall())
    computed_state = compute_session_state_from_rows(session_row, task_rows, memory_rows)
    refreshed_state = upsert_computed_session_state(cur, session_id, computed_state)
    return session_row, task_rows, memory_rows, refreshed_state


def load_session_health_context(
    cur,
    session_id: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None, list[dict[str, Any]]]:
    session_row, task_rows, memory_rows, session_state_row = load_session_review_context(cur, session_id)
    cur.execute(
        """
        SELECT id, session_id, review_kind, summary_text, highlights, open_loops, created_at
        FROM session_reviews
        WHERE session_id = %s
        ORDER BY created_at DESC, id DESC;
        """,
        (session_id,),
    )
    review_rows = list(cur.fetchall())
    return session_row, task_rows, memory_rows, session_state_row, review_rows


def insert_session_review_row(
    cur,
    session_id: int,
    review_kind: str,
    built_review: dict[str, Any],
) -> dict[str, Any]:
    cur.execute(
        """
        INSERT INTO session_reviews (session_id, review_kind, summary_text, highlights, open_loops)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id, session_id, review_kind, summary_text, highlights, open_loops, created_at;
        """,
        (
            session_id,
            review_kind,
            built_review["summary_text"],
            safe_json_dumps(built_review["highlights"]),
            safe_json_dumps(built_review["open_loops"]),
        ),
    )
    return cur.fetchone()


def merge_memory_into_session_state(
    cur,
    session_id: int,
    category: str,
    content: str,
) -> dict[str, Any] | None:
    normalized_category = category.strip().lower()
    normalized_content = content.strip()
    if not normalized_content:
        return None
    if normalized_category not in {"preference", "open_loop", "todo", "follow_up"}:
        return None

    cur.execute(
        """
        SELECT session_id, summary_text, preferences, open_loops, created_at, updated_at
        FROM session_states
        WHERE session_id = %s;
        """,
        (session_id,),
    )
    row = cur.fetchone()
    if row:
        state = serialize_session_state_row(row)
    else:
        state = {
            "session_id": session_id,
            "summary_text": "",
            "preferences": [],
            "open_loops": [],
            "created_at": None,
            "updated_at": None,
        }

    preferences = [str(item).strip() for item in state["preferences"] if str(item).strip()]
    open_loops = [str(item).strip() for item in state["open_loops"] if str(item).strip()]

    if normalized_category == "preference":
        if normalized_content not in preferences:
            preferences.append(normalized_content)
    elif normalized_content not in open_loops:
        open_loops.append(normalized_content)

    cur.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM task_runs
        WHERE session_id = %s
        GROUP BY status
        ORDER BY status ASC;
        """,
        (session_id,),
    )
    tasks_by_status = {str(row["status"]): int(row["count"]) for row in cur.fetchall()}
    total_tasks = sum(tasks_by_status.values())

    session_name = ""
    cur.execute("SELECT name FROM sessions WHERE id = %s;", (session_id,))
    session_row = cur.fetchone()
    if session_row:
        session_name = str(session_row.get("name") or "").strip()

    summary_parts = [f"Session: {session_name or session_id}", f"tasks={total_tasks}"]
    if tasks_by_status:
        summary_parts.append(
            "statuses=" + ", ".join(f"{key}:{value}" for key, value in sorted(tasks_by_status.items()))
        )
    if preferences:
        summary_parts.append(f"preferences={len(preferences)}")
    if open_loops:
        summary_parts.append(f"open_loops={len(open_loops)}")
    summary_text = " | ".join(summary_parts)

    cur.execute(
        """
        INSERT INTO session_states (session_id, summary_text, preferences, open_loops)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (session_id) DO UPDATE
        SET summary_text = EXCLUDED.summary_text,
            preferences = EXCLUDED.preferences,
            open_loops = EXCLUDED.open_loops,
            updated_at = CURRENT_TIMESTAMP
        RETURNING session_id, summary_text, preferences, open_loops, created_at, updated_at;
        """,
        (
            session_id,
            summary_text,
            safe_json_dumps(preferences),
            safe_json_dumps(open_loops),
        ),
    )
    return serialize_session_state_row(cur.fetchone())


def refresh_session_task_summary_memories(cur, task_rows: list[dict[str, Any]]):
    for row in task_rows:
        task_id = row.get("id")
        session_id = row.get("session_id")
        if not task_id or not session_id:
            continue
        final_result = str(row.get("result") or "").strip()
        if not final_result:
            continue

        runtime_overrides = _parse_maybe_json(row.get("runtime_overrides")) or {}
        task_display_input = build_task_display_user_input(str(row.get("user_input") or ""), runtime_overrides)
        task_summary_content = build_task_summary_memory_content(task_display_input, final_result)
        fact_content = build_task_fact_memory_content(final_result)

        cur.execute(
            """
            UPDATE session_memories
            SET content = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE session_id = %s
              AND source_task_id = %s
              AND category = 'task_summary';
            """,
            (task_summary_content, session_id, task_id),
        )
        if fact_content:
            cur.execute(
                """
                UPDATE session_memories
                SET content = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE session_id = %s
                  AND source_task_id = %s
                  AND category = 'fact';
                """,
                (fact_content, session_id, task_id),
            )


def extract_review_note_from_highlights(highlights: list[Any]) -> str:
    for item in highlights:
        text = str(item or "").strip()
        if text.startswith("备注："):
            return text.split("备注：", 1)[1].strip()
    return ""


def refresh_session_reviews(
    cur,
    *,
    session_row: dict[str, Any],
    task_rows: list[dict[str, Any]],
    memory_rows: list[dict[str, Any]],
    session_state_row: dict[str, Any] | None,
):
    cur.execute(
        """
        SELECT id, summary_text, highlights, open_loops
        FROM session_reviews
        WHERE session_id = %s
        ORDER BY id ASC;
        """,
        (session_row["id"],),
    )
    review_rows = list(cur.fetchall())
    for review_row in review_rows:
        note = extract_review_note_from_highlights(_parse_maybe_json(review_row.get("highlights")) or [])
        rebuilt = build_session_review(session_row, task_rows, memory_rows, session_state_row, note)
        cur.execute(
            """
            UPDATE session_reviews
            SET summary_text = %s,
                highlights = %s,
                open_loops = %s
            WHERE id = %s;
            """,
            (
                rebuilt["summary_text"],
                safe_json_dumps(rebuilt["highlights"]),
                safe_json_dumps(rebuilt["open_loops"]),
                review_row["id"],
            ),
        )
