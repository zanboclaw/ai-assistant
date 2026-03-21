from typing import Any


def _fetch_count(cur, query: str, params: tuple[Any, ...] | None = None) -> int:
    cur.execute(query, params or ())
    row = cur.fetchone() or {}
    return int(row.get("count") or 0)


def fetch_monitor_overview_snapshot(
    cur,
    *,
    parse_maybe_json_fn,
    serialize_session_review_row_fn,
    serialize_agent_run_row_fn,
    serialize_evaluator_run_row_fn,
    list_workflow_proposals_rows_fn,
) -> dict[str, Any]:
    cur.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM task_runs
        GROUP BY status
        ORDER BY status ASC;
        """
    )
    tasks_by_status = {str(row["status"]): int(row["count"]) for row in cur.fetchall()}

    total_tasks = _fetch_count(cur, "SELECT COUNT(*) AS count FROM task_runs;")
    total_sessions = _fetch_count(cur, "SELECT COUNT(*) AS count FROM sessions;")
    total_memories = _fetch_count(cur, "SELECT COUNT(*) AS count FROM session_memories;")
    total_session_states = _fetch_count(cur, "SELECT COUNT(*) AS count FROM session_states;")
    total_session_reviews = _fetch_count(cur, "SELECT COUNT(*) AS count FROM session_reviews;")

    sessions_missing_state_count = _fetch_count(
        cur,
        """
        SELECT COUNT(*) AS count
        FROM sessions s
        LEFT JOIN session_states st ON st.session_id = s.id
        WHERE st.session_id IS NULL;
        """,
    )
    sessions_missing_review_count = _fetch_count(
        cur,
        """
        SELECT COUNT(*) AS count
        FROM sessions s
        LEFT JOIN (
            SELECT DISTINCT session_id
            FROM session_reviews
        ) sr ON sr.session_id = s.id
        WHERE sr.session_id IS NULL;
        """,
    )
    active_session_count = _fetch_count(
        cur,
        """
        SELECT COUNT(DISTINCT session_id) AS count
        FROM task_runs
        WHERE session_id IS NOT NULL
          AND status IN ('pending', 'running', 'waiting_approval', 'paused', 'interrupt_requested');
        """,
    )
    sessions_needing_review_count = _fetch_count(
        cur,
        """
        SELECT COUNT(*) AS count
        FROM (
            SELECT DISTINCT t.session_id
            FROM task_runs t
            LEFT JOIN (
                SELECT session_id, MAX(created_at) AS last_daily_review_at
                FROM session_reviews
                WHERE review_kind = 'daily'
                  AND DATE(created_at) = CURRENT_DATE
                GROUP BY session_id
            ) dr ON dr.session_id = t.session_id
            WHERE t.session_id IS NOT NULL
              AND t.status IN ('pending', 'running', 'waiting_approval', 'paused', 'interrupt_requested')
              AND dr.session_id IS NULL
        ) session_review_gap;
        """,
    )
    sessions_with_duplicate_memories_count = _fetch_count(
        cur,
        """
        SELECT COUNT(*) AS count
        FROM (
            SELECT session_id
            FROM session_memories
            GROUP BY session_id, LOWER(TRIM(category)), LOWER(TRIM(content))
            HAVING COUNT(*) > 1
        ) duplicate_memories;
        """,
    )
    sessions_with_open_loops_count = _fetch_count(
        cur,
        """
        SELECT COUNT(*) AS count
        FROM session_states
        WHERE jsonb_array_length(COALESCE(open_loops::jsonb, '[]'::jsonb)) > 0;
        """,
    )
    daily_reviews_today = _fetch_count(
        cur,
        """
        SELECT COUNT(*) AS count
        FROM session_reviews
        WHERE review_kind = 'daily'
          AND DATE(created_at) = CURRENT_DATE;
        """,
    )
    pending_approvals = _fetch_count(cur, "SELECT COUNT(*) AS count FROM approvals WHERE status = 'pending';")
    risk_policy_count = _fetch_count(cur, "SELECT COUNT(*) AS count FROM risk_policies;")
    tool_registry_count = _fetch_count(cur, "SELECT COUNT(*) AS count FROM tool_registry_entries;")
    disabled_tool_count = _fetch_count(
        cur,
        "SELECT COUNT(*) AS count FROM tool_registry_entries WHERE enabled = FALSE;",
    )
    model_route_count = _fetch_count(cur, "SELECT COUNT(*) AS count FROM model_routes;")
    disabled_model_route_count = _fetch_count(
        cur,
        "SELECT COUNT(*) AS count FROM model_routes WHERE enabled = FALSE;",
    )
    model_provider_count = _fetch_count(cur, "SELECT COUNT(*) AS count FROM model_providers;")
    disabled_model_provider_count = _fetch_count(
        cur,
        "SELECT COUNT(*) AS count FROM model_providers WHERE enabled = FALSE;",
    )
    total_change_requests = _fetch_count(cur, "SELECT COUNT(*) AS count FROM change_requests;")
    total_agent_runs = _fetch_count(cur, "SELECT COUNT(*) AS count FROM agent_runs;")

    cur.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM agent_runs
        GROUP BY status
        ORDER BY status ASC;
        """
    )
    agent_runs_by_status = {str(row["status"]): int(row["count"]) for row in cur.fetchall()}

    cur.execute(
        """
        SELECT role, COUNT(*) AS count
        FROM agent_runs
        GROUP BY role
        ORDER BY role ASC;
        """
    )
    agent_runs_by_role = {str(row["role"]): int(row["count"]) for row in cur.fetchall()}

    total_agent_messages = _fetch_count(cur, "SELECT COUNT(*) AS count FROM agent_messages;")
    total_agent_artifacts = _fetch_count(cur, "SELECT COUNT(*) AS count FROM agent_artifacts;")

    cur.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM change_requests
        GROUP BY status;
        """
    )
    change_request_status_counts = {str(row["status"]): int(row["count"]) for row in cur.fetchall()}
    pending_change_requests = int(change_request_status_counts.get("pending", 0))
    approved_change_requests = int(change_request_status_counts.get("approved", 0))
    rejected_change_requests = int(change_request_status_counts.get("rejected", 0))
    applied_change_requests = int(change_request_status_counts.get("applied", 0))
    closed_change_requests = rejected_change_requests + applied_change_requests
    change_request_closure_ratio = round(closed_change_requests / total_change_requests, 3) if total_change_requests else 0.0

    access_actor_count = _fetch_count(cur, "SELECT COUNT(*) AS count FROM access_actors;")
    access_quota_count = _fetch_count(cur, "SELECT COUNT(*) AS count FROM access_quotas;")
    quota_pressure_count = _fetch_count(
        cur,
        """
        SELECT COUNT(*) AS count
        FROM (
            SELECT a.actor_name
            FROM access_actors a
            JOIN access_quotas q ON q.actor_name = a.actor_name
            LEFT JOIN (
                SELECT created_by_actor, COUNT(*) AS daily_task_count
                FROM task_runs
                WHERE created_by_actor IS NOT NULL
                  AND DATE(created_at) = CURRENT_DATE
                GROUP BY created_by_actor
            ) d ON d.created_by_actor = a.actor_name
            LEFT JOIN (
                SELECT created_by_actor, COUNT(*) AS active_task_count
                FROM task_runs
                WHERE created_by_actor IS NOT NULL
                  AND status NOT IN ('completed', 'failed')
                GROUP BY created_by_actor
            ) ac ON ac.created_by_actor = a.actor_name
            WHERE COALESCE(d.daily_task_count, 0) >= q.daily_task_limit
               OR COALESCE(ac.active_task_count, 0) >= q.active_task_limit
        ) quota_pressure;
        """,
    )
    cur.execute(
        """
        SELECT role, COUNT(*) AS count
        FROM access_actors
        GROUP BY role
        ORDER BY role ASC;
        """
    )
    actors_by_role = {str(row["role"]): int(row["count"]) for row in cur.fetchall()}

    checkpointed_tasks = _fetch_count(
        cur,
        """
        SELECT COUNT(*) AS count
        FROM task_runs
        WHERE checkpoint_path IS NOT NULL AND checkpoint_path != '';
        """,
    )

    cur.execute(
        """
        SELECT id, task_id, event_type, actor, details, created_at
        FROM audit_logs
        ORDER BY id DESC
        LIMIT 8;
        """
    )
    recent_audit_logs = list(cur.fetchall())
    for row in recent_audit_logs:
        row["details"] = parse_maybe_json_fn(row.get("details"))

    cur.execute(
        """
        SELECT id, user_input, status, updated_at
        FROM task_runs
        ORDER BY updated_at DESC, id DESC
        LIMIT 8;
        """
    )
    recent_tasks = list(cur.fetchall())

    cur.execute(
        """
        SELECT id, session_id, review_kind, summary_text, highlights, open_loops, created_at
        FROM session_reviews
        ORDER BY id DESC
        LIMIT 5;
        """
    )
    recent_reviews = [serialize_session_review_row_fn(row) for row in cur.fetchall()]

    cur.execute(
        """
        SELECT id, task_run_id, parent_agent_run_id, role, status, attempt, assigned_model,
               execution_mode, execution_request_json, source_task_run_id, assigned_step_orders_json,
               assigned_tool_profile, error_summary, cost_tokens_in, cost_tokens_out,
               cost_usd_estimate, created_at, updated_at, started_at, completed_at
        FROM agent_runs
        ORDER BY id DESC
        LIMIT 6;
        """
    )
    recent_agent_runs = [serialize_agent_run_row_fn(row) for row in cur.fetchall()]

    total_evaluator_runs = _fetch_count(cur, "SELECT COUNT(*) AS count FROM evaluator_runs;")
    cur.execute(
        """
        SELECT decision, COUNT(*) AS count
        FROM evaluator_runs
        GROUP BY decision
        ORDER BY decision ASC;
        """
    )
    evaluator_runs_by_decision = {str(row["decision"]): int(row["count"]) for row in cur.fetchall()}
    cur.execute(
        """
        SELECT failure_reason, COUNT(*) AS count
        FROM evaluator_runs
        GROUP BY failure_reason
        ORDER BY failure_reason ASC;
        """
    )
    evaluator_runs_by_reason = {str(row["failure_reason"]): int(row["count"]) for row in cur.fetchall()}
    cur.execute(
        """
        SELECT AVG(score) AS avg_score
        FROM evaluator_runs;
        """
    )
    avg_evaluator_score_row = cur.fetchone()
    avg_evaluator_score = (
        float(avg_evaluator_score_row["avg_score"])
        if avg_evaluator_score_row and avg_evaluator_score_row["avg_score"] is not None
        else None
    )
    cur.execute(
        """
        SELECT id, task_run_id, manager_agent_run_id, reviewer_agent_run_id, final_artifact_id, review_artifact_id,
               evaluator_kind, status, decision, score, failure_reason, failure_stage,
               criteria_json, step_stats_json, proposal_json, summary, recommendation,
               source, created_at
        FROM evaluator_runs
        ORDER BY id DESC
        LIMIT 6;
        """
    )
    recent_evaluator_runs = [serialize_evaluator_run_row_fn(row) for row in cur.fetchall()]
    workflow_proposal_rows = list_workflow_proposals_rows_fn(cur, limit=6)
    workflow_proposals_by_action: dict[str, int] = {}
    workflow_proposals_by_priority: dict[str, int] = {}
    for proposal in workflow_proposal_rows:
        action_key = str(proposal.get("action_key") or "unknown")
        priority_key = str(proposal.get("priority") or "unknown")
        workflow_proposals_by_action[action_key] = int(workflow_proposals_by_action.get(action_key, 0)) + 1
        workflow_proposals_by_priority[priority_key] = int(workflow_proposals_by_priority.get(priority_key, 0)) + 1

    total_workflow_proposals = _fetch_count(
        cur,
        """
        SELECT COUNT(*) AS count
        FROM evaluator_runs
        WHERE proposal_json IS NOT NULL
          AND proposal_json != '';
        """,
    )
    cur.execute(
        """
        SELECT MAX(created_at) AS last_daily_review_at
        FROM session_reviews
        WHERE review_kind = 'daily';
        """
    )
    last_daily_review_at_row = cur.fetchone()
    last_daily_review_at = last_daily_review_at_row["last_daily_review_at"] if last_daily_review_at_row else None

    return {
        "tasks_by_status": tasks_by_status,
        "total_tasks": total_tasks,
        "total_sessions": total_sessions,
        "total_memories": total_memories,
        "total_session_states": total_session_states,
        "total_session_reviews": total_session_reviews,
        "sessions_missing_state_count": sessions_missing_state_count,
        "sessions_missing_review_count": sessions_missing_review_count,
        "active_session_count": active_session_count,
        "sessions_needing_review_count": sessions_needing_review_count,
        "sessions_with_duplicate_memories_count": sessions_with_duplicate_memories_count,
        "sessions_with_open_loops_count": sessions_with_open_loops_count,
        "daily_reviews_today": daily_reviews_today,
        "last_daily_review_at": last_daily_review_at,
        "pending_approvals": pending_approvals,
        "risk_policy_count": risk_policy_count,
        "tool_registry_count": tool_registry_count,
        "disabled_tool_count": disabled_tool_count,
        "model_route_count": model_route_count,
        "disabled_model_route_count": disabled_model_route_count,
        "model_provider_count": model_provider_count,
        "disabled_model_provider_count": disabled_model_provider_count,
        "total_change_requests": total_change_requests,
        "change_request_status_counts": change_request_status_counts,
        "pending_change_requests": pending_change_requests,
        "approved_change_requests": approved_change_requests,
        "rejected_change_requests": rejected_change_requests,
        "applied_change_requests": applied_change_requests,
        "closed_change_requests": closed_change_requests,
        "change_request_closure_ratio": change_request_closure_ratio,
        "access_actor_count": access_actor_count,
        "access_quota_count": access_quota_count,
        "quota_pressure_count": quota_pressure_count,
        "actors_by_role": actors_by_role,
        "checkpointed_tasks": checkpointed_tasks,
        "recent_audit_logs": recent_audit_logs,
        "recent_tasks": recent_tasks,
        "recent_reviews": recent_reviews,
        "total_agent_runs": total_agent_runs,
        "agent_runs_by_status": agent_runs_by_status,
        "agent_runs_by_role": agent_runs_by_role,
        "total_agent_messages": total_agent_messages,
        "total_agent_artifacts": total_agent_artifacts,
        "recent_agent_runs": recent_agent_runs,
        "total_evaluator_runs": total_evaluator_runs,
        "evaluator_runs_by_decision": evaluator_runs_by_decision,
        "evaluator_runs_by_reason": evaluator_runs_by_reason,
        "avg_evaluator_score": avg_evaluator_score,
        "recent_evaluator_runs": recent_evaluator_runs,
        "workflow_proposal_rows": workflow_proposal_rows,
        "workflow_proposals_by_action": workflow_proposals_by_action,
        "workflow_proposals_by_priority": workflow_proposals_by_priority,
        "total_workflow_proposals": total_workflow_proposals,
    }
