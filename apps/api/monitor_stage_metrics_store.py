from typing import Any


def _fetch_count(cur, query: str, params: tuple[Any, ...] | None = None) -> int:
    cur.execute(query, params or ())
    row = cur.fetchone() or {}
    return int(row.get("count") or 0)


def fetch_stage56_overview_metrics(
    cur,
    *,
    fetch_task_agent_summary_fn,
    specialist_execution_modes: list[str],
    specialist_tool_profiles: list[str],
) -> dict[str, Any]:
    cur.execute(
        """
        SELECT DISTINCT task_run_id
        FROM agent_runs
        ORDER BY task_run_id DESC
        LIMIT 120;
        """
    )
    stage5_task_ids = [int(row["task_run_id"]) for row in cur.fetchall() if row.get("task_run_id") is not None]
    stage5_summary_rows = [fetch_task_agent_summary_fn(cur, task_id) for task_id in stage5_task_ids]

    tasks_requiring_execute = sum(1 for item in stage5_summary_rows if item.get("recommended_action") == "execute")
    tasks_requiring_finalize = sum(1 for item in stage5_summary_rows if item.get("recommended_action") == "finalize")
    tasks_requiring_retry = sum(
        1 for item in stage5_summary_rows if item.get("recommended_action") in {"rerun_specialists", "finalize_retry"}
    )
    tasks_requiring_operator_escalation = sum(
        1 for item in stage5_summary_rows if item.get("recommended_action") == "escalate_operator"
    )

    mainline_stage5_summary_rows = [
        item
        for item in stage5_summary_rows
        if item.get("implementation_status") == "task_runtime_postrun_v1"
        and item.get("execution_backend") == "mainline"
    ]
    stage5_mainline_task_count = len(mainline_stage5_summary_rows)
    stage5_runtime_fanout_task_count = sum(1 for item in mainline_stage5_summary_rows if bool(item.get("runtime_fanout_active")))
    stage5_role_skeleton_ready_count = sum(
        1
        for item in mainline_stage5_summary_rows
        if int(((item.get("role_counts") or {}).get("manager") or 0)) >= 1
        and int(((item.get("role_counts") or {}).get("specialist") or 0)) >= 1
        and int(((item.get("role_counts") or {}).get("reviewer") or 0)) >= 1
    )
    terminal_mainline_stage5_rows = [
        item for item in mainline_stage5_summary_rows if item.get("latest_evaluator_source") == "task_runtime_postrun_v1"
    ]
    stage5_terminal_mainline_task_count = len(terminal_mainline_stage5_rows)
    stage5_terminal_ready_count = sum(
        1
        for item in terminal_mainline_stage5_rows
        if bool(item.get("runtime_fanout_active"))
        and int(((item.get("role_counts") or {}).get("manager") or 0)) >= 1
        and int(((item.get("role_counts") or {}).get("specialist") or 0)) >= 1
        and int(((item.get("role_counts") or {}).get("reviewer") or 0)) >= 1
        and bool((item.get("latest_final_artifact") or {}).get("id"))
        and bool(item.get("latest_workflow_proposal_action"))
    )

    stage5_non_readonly_specialist_task_count = _fetch_count(
        cur,
        """
        SELECT COUNT(DISTINCT task_run_id) AS count
        FROM agent_runs
        WHERE task_run_id IS NOT NULL
          AND role = 'specialist'
          AND execution_mode = ANY(%s)
          AND assigned_tool_profile = ANY(%s)
          AND (
            CASE
              WHEN execution_request_json IS NULL OR BTRIM(execution_request_json) = '' THEN 'readonly_step_digest'
              ELSE COALESCE(execution_request_json::jsonb ->> 'subtask_type', 'readonly_step_digest')
            END
          ) NOT LIKE 'readonly_%%';
        """,
        (specialist_execution_modes, specialist_tool_profiles),
    )

    specialist_subtasks_by_type: dict[str, int] = {}
    for item in stage5_summary_rows:
        for specialist in item.get("specialists") or []:
            subtask_type = str(specialist.get("subtask_type") or "readonly_step_digest")
            specialist_subtasks_by_type[subtask_type] = int(specialist_subtasks_by_type.get(subtask_type, 0)) + 1

    stage6_mainline_evaluator_run_count = _fetch_count(
        cur,
        """
        SELECT COUNT(*) AS count
        FROM evaluator_runs
        WHERE source = 'task_runtime_postrun_v1';
        """,
    )
    stage6_mainline_workflow_proposal_count = _fetch_count(
        cur,
        """
        SELECT COUNT(*) AS count
        FROM evaluator_runs
        WHERE source = 'task_runtime_postrun_v1'
          AND proposal_json IS NOT NULL
          AND proposal_json != '';
        """,
    )
    stage6_auto_mapped_proposal_count = _fetch_count(
        cur,
        """
        SELECT COUNT(*) AS count
        FROM evaluator_runs
        WHERE source = 'task_runtime_postrun_v1'
          AND proposal_json IS NOT NULL
          AND proposal_json != ''
          AND proposal_json::jsonb ->> 'action_key' = 'expand_specialist_scope';
        """,
    )
    stage6_mainline_bridged_change_request_count = _fetch_count(
        cur,
        """
        SELECT COUNT(*) AS count
        FROM audit_logs
        WHERE event_type = 'workflow_proposal.change_request_create'
          AND EXISTS (
              SELECT 1
              FROM evaluator_runs
              WHERE evaluator_runs.id = NULLIF(audit_logs.details ->> 'proposal_id', '')::int
                AND evaluator_runs.source = 'task_runtime_postrun_v1'
          );
        """,
    )

    cur.execute(
        """
        SELECT event_type, COUNT(*) AS count
        FROM audit_logs
        WHERE event_type IN (
            'agent.mainline_runtime_fanout',
            'agent.mainline_runtime_fanin',
            'agent.mainline_runtime_execute',
            'workflow_proposal.shadow_validation',
            'workflow_proposal.shadow_validated'
        )
        GROUP BY event_type;
        """
    )
    stage56_audit_counts = {str(row["event_type"]): int(row["count"]) for row in cur.fetchall()}
    stage5_runtime_fanout_event_count = int(stage56_audit_counts.get("agent.mainline_runtime_fanout", 0))
    stage5_runtime_fanin_event_count = int(stage56_audit_counts.get("agent.mainline_runtime_fanin", 0))
    stage5_runtime_execute_event_count = int(stage56_audit_counts.get("agent.mainline_runtime_execute", 0))
    stage6_shadow_validation_count = int(stage56_audit_counts.get("workflow_proposal.shadow_validation", 0)) + int(
        stage56_audit_counts.get("workflow_proposal.shadow_validated", 0)
    )

    cur.execute(
        """
        SELECT DISTINCT task_id, event_type
        FROM audit_logs
        WHERE task_id IS NOT NULL
          AND event_type IN (
              'agent.mainline_runtime_fanout',
              'agent.mainline_runtime_fanin',
              'agent.mainline_runtime_execute'
          );
        """
    )
    stage56_audit_task_rows = cur.fetchall()
    stage5_runtime_fanout_task_ids = {
        int(row["task_id"])
        for row in stage56_audit_task_rows
        if row.get("task_id") is not None and row.get("event_type") == "agent.mainline_runtime_fanout"
    }
    stage5_runtime_fanin_task_ids = {
        int(row["task_id"])
        for row in stage56_audit_task_rows
        if row.get("task_id") is not None and row.get("event_type") == "agent.mainline_runtime_fanin"
    }
    stage5_runtime_execute_task_ids = {
        int(row["task_id"])
        for row in stage56_audit_task_rows
        if row.get("task_id") is not None and row.get("event_type") == "agent.mainline_runtime_execute"
    }

    stage5_runtime_fanout_task_count = sum(
        1
        for item in mainline_stage5_summary_rows
        if bool(item.get("runtime_fanout_active")) or int(item.get("task_id") or 0) in stage5_runtime_fanout_task_ids
    )
    stage5_terminal_ready_count = sum(
        1
        for item in terminal_mainline_stage5_rows
        if int(((item.get("role_counts") or {}).get("manager") or 0)) >= 1
        and int(((item.get("role_counts") or {}).get("specialist") or 0)) >= 1
        and int(((item.get("role_counts") or {}).get("reviewer") or 0)) >= 1
        and bool((item.get("latest_final_artifact") or {}).get("id"))
        and bool(item.get("latest_workflow_proposal_action"))
        and int(item.get("task_id") or 0) in stage5_runtime_fanout_task_ids
        and int(item.get("task_id") or 0) in stage5_runtime_fanin_task_ids
        and int(item.get("task_id") or 0) in stage5_runtime_execute_task_ids
    )

    stage6_failure_taxonomy_count = _fetch_count(
        cur,
        """
        SELECT COUNT(*) AS count
        FROM evaluator_runs
        WHERE source = 'task_runtime_postrun_v1'
          AND COALESCE(failure_reason, '') != ''
          AND COALESCE(failure_stage, '') != '';
        """,
    )

    return {
        "stage5_summary_rows": stage5_summary_rows,
        "tasks_requiring_execute": tasks_requiring_execute,
        "tasks_requiring_finalize": tasks_requiring_finalize,
        "tasks_requiring_retry": tasks_requiring_retry,
        "tasks_requiring_operator_escalation": tasks_requiring_operator_escalation,
        "stage5_mainline_task_count": stage5_mainline_task_count,
        "stage5_runtime_fanout_task_count": stage5_runtime_fanout_task_count,
        "stage5_role_skeleton_ready_count": stage5_role_skeleton_ready_count,
        "stage5_terminal_mainline_task_count": stage5_terminal_mainline_task_count,
        "stage5_terminal_ready_count": stage5_terminal_ready_count,
        "stage5_non_readonly_specialist_task_count": stage5_non_readonly_specialist_task_count,
        "specialist_subtasks_by_type": specialist_subtasks_by_type,
        "stage6_mainline_evaluator_run_count": stage6_mainline_evaluator_run_count,
        "stage6_mainline_workflow_proposal_count": stage6_mainline_workflow_proposal_count,
        "stage6_auto_mapped_proposal_count": stage6_auto_mapped_proposal_count,
        "stage6_mainline_bridged_change_request_count": stage6_mainline_bridged_change_request_count,
        "stage5_runtime_fanout_event_count": stage5_runtime_fanout_event_count,
        "stage5_runtime_fanin_event_count": stage5_runtime_fanin_event_count,
        "stage5_runtime_execute_event_count": stage5_runtime_execute_event_count,
        "stage6_shadow_validation_count": stage6_shadow_validation_count,
        "stage6_failure_taxonomy_count": stage6_failure_taxonomy_count,
    }
