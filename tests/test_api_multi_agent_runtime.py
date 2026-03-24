from __future__ import annotations

from copy import deepcopy
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1] / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from api_multi_agent_runtime import (
    build_specialist_step_partitions,
    build_task_agent_summary_payload,
    fetch_task_agent_summary,
)


class FakeCursor:
    def __init__(self, *, fetchone_results=None, fetchall_results=None):
        self.fetchone_results = list(fetchone_results or [])
        self.fetchall_results = list(fetchall_results or [])
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((" ".join(str(sql).split()), params))

    def fetchone(self):
        if self.fetchone_results:
            return deepcopy(self.fetchone_results.pop(0))
        return None

    def fetchall(self):
        if self.fetchall_results:
            return deepcopy(self.fetchall_results.pop(0))
        return []


def test_build_task_agent_summary_payload_marks_mainline_validation_failure():
    payload = build_task_agent_summary_payload(
        task_id=42,
        agent_rows=[
            {"id": 1, "role": "manager", "status": "completed"},
            {
                "id": 2,
                "role": "specialist",
                "status": "completed",
                "attempt": 1,
                "output_artifact_id": 11,
                "review_artifact_id": None,
                "execution_mode": "task_runtime_worker_v1",
                "execution_request": {"subtask_type": "readonly_source_snapshot"},
                "assigned_step_orders": [1, 2],
                "assigned_model": "specialist-a",
                "assigned_tool_profile": "specialist-readonly",
            },
        ],
        artifact_rows=[
            {
                "id": 11,
                "artifact_type": "final",
                "version": 1,
                "content": {
                    "review_status": "approved",
                    "next_strategy": "expand",
                    "quality_score": 95,
                },
            }
        ],
        serialize_agent_run_row=lambda row: {"id": row["id"], "role": row["role"], "status": row["status"]},
        multi_agent_protocol_version="multi-agent-v1",
        mainline_specialist_execution_modes={"task_runtime_worker_v1", "task_postrun_readonly_v1"},
        latest_evaluator={
            "source": "task_runtime_postrun_v1",
            "recommendation": "repair",
            "failure_reason": "reviewer_rejected",
            "failure_stage": "review",
            "workflow_proposal": {"action_key": "repair_failed_steps", "priority": "high"},
        },
        validation_report={"passed": False, "summary": "deliverable invalid"},
        recovery_action={"action": "repair_failed_steps", "summary": "retry failed path"},
    )

    assert payload["execution_backend"] == "mainline"
    assert payload["record_origin"] == "mainline_postrun"
    assert payload["recommended_action"] == "repair_failed_steps"
    assert payload["awaiting_role"] == "operator"
    assert payload["latest_failure_reason"] == "deliverable_validation_failed"
    assert payload["latest_workflow_proposal_action"] == "repair_failed_steps"


def test_fetch_task_agent_summary_loads_rows_and_delegates_payload_build():
    cursor = FakeCursor(
        fetchone_results=[
            {
                "validation_report_json": {"passed": True},
                "recovery_action_json": {"action": "none"},
            }
        ],
        fetchall_results=[
            [{"id": 1, "role": "manager", "status": "completed"}],
            [{"id": 9, "artifact_type": "final", "content_json": {"review_status": "approved"}}],
        ],
    )
    payload_calls = []

    result = fetch_task_agent_summary(
        cursor,
        7,
        serialize_agent_run_row=lambda row: {"id": row["id"], "role": row["role"], "status": row["status"]},
        serialize_agent_artifact_row=lambda row: {
            "id": row["id"],
            "artifact_type": row["artifact_type"],
            "content": row.get("content_json") or {},
        },
        fetch_latest_evaluator_for_task_fn=lambda _cur, task_id: {"task_id": task_id, "source": "demo"},
        build_task_agent_summary_payload_fn=lambda **kwargs: payload_calls.append(kwargs) or {
            "task_id": kwargs["task_id"],
            "agent_count": len(kwargs["agent_rows"]),
            "artifact_count": len(kwargs["artifact_rows"]),
            "validation_report": kwargs["validation_report"],
            "recovery_action": kwargs["recovery_action"],
        },
        parse_maybe_json=lambda value: value,
    )

    assert result["task_id"] == 7
    assert result["agent_count"] == 1
    assert result["artifact_count"] == 1
    assert result["validation_report"]["passed"] is True
    assert payload_calls[0]["latest_evaluator"]["task_id"] == 7
    assert len(cursor.executed) == 3


def test_build_specialist_step_partitions_falls_back_to_task_snapshot():
    outline, partitions, status_counts = build_specialist_step_partitions(
        step_rows=[],
        specialist_count=2,
        task_row={
            "status": "failed",
            "user_input": "scan repo",
            "result": "partial result",
            "error_message": "network error",
        },
        build_task_display_input_excerpt=lambda row: f"input:{row['user_input']}",
        build_task_result_excerpt=lambda row: f"result:{row['result']}",
    )

    assert outline == []
    assert len(partitions) == 2
    assert partitions[0][0]["step_name"] == "task-result-fallback"
    assert partitions[0][0]["input_excerpt"] == "input:scan repo"
    assert partitions[0][0]["output_excerpt"] == "result:partial result"
    assert status_counts == {}
