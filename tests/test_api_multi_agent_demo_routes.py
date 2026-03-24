from __future__ import annotations

from copy import deepcopy

from fastapi import FastAPI
from fastapi.testclient import TestClient

import multi_agent_demo_routes


class DemoCursor:
    def __init__(self, scenario: dict):
        self.scenario = scenario
        self._fetchone = None
        self._fetchall = []

    def execute(self, sql, params=None):
        normalized = " ".join(str(sql).split())
        params = params or ()

        if "FROM task_runs" in normalized and "session_id" in normalized:
            self._fetchone = deepcopy(self.scenario.get("bootstrap_task_row"))
            self._fetchall = []
            return

        if "SELECT COUNT(*) AS count FROM agent_runs" in normalized:
            self._fetchone = {"count": self.scenario.get("agent_run_count", 0)}
            self._fetchall = []
            return

        if "FROM task_runs" in normalized and "result, error_message" in normalized:
            self._fetchone = deepcopy(self.scenario.get("task_row"))
            self._fetchall = []
            return

        if "SELECT id, user_input, status, runtime_overrides FROM task_runs" in normalized:
            self._fetchone = deepcopy(self.scenario.get("task_row"))
            self._fetchall = []
            return

        if "FROM agent_runs" in normalized and "ORDER BY id ASC;" in normalized:
            self._fetchall = deepcopy(self.scenario.get("agent_rows", []))
            self._fetchone = None
            return

        if "FROM task_steps" in normalized:
            self._fetchall = deepcopy(self.scenario.get("step_rows", []))
            self._fetchone = None
            return

        if "FROM agent_artifacts" in normalized:
            self._fetchall = deepcopy(self.scenario.get("artifact_rows", []))
            self._fetchone = None
            return

        self._fetchone = None
        self._fetchall = []

    def fetchone(self):
        return deepcopy(self._fetchone)

    def fetchall(self):
        return deepcopy(self._fetchall)

    def close(self):
        return None


class DemoConn:
    def __init__(self, cursor: DemoCursor):
        self._cursor = cursor
        self.commit_called = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commit_called += 1

    def close(self):
        return None


class FakeLogger:
    def __init__(self):
        self.messages = []

    def info(self, message, *args):
        self.messages.append(message % args if args else message)


def build_client(scenario: dict):
    cursor = DemoCursor(scenario)
    conn = DemoConn(cursor)
    logger = FakeLogger()
    scenario["audit_logs"] = []
    scenario["agent_messages"] = []
    scenario["enqueued_runs"] = []
    next_ids = {"artifact": 100, "run": 200, "message": 300, "evaluator": 400}

    def next_id(kind: str) -> int:
        next_ids[kind] += 1
        return next_ids[kind]

    app = FastAPI()
    app.include_router(
        multi_agent_demo_routes.register_multi_agent_demo_routes(
            get_conn=lambda: conn,
            require_actor_permission=lambda _cur, actor_name, permission: {
                "actor_name": actor_name or "local_admin",
                "role": "admin",
                "permission": permission,
            },
            ensure_agent_tables=lambda _cur: None,
            build_task_display_user_input=lambda user_input, _overrides: user_input,
            parse_maybe_json=lambda value: value if not isinstance(value, str) else {},
            multi_agent_protocol_version="multi-agent-v1",
            create_agent_artifact=lambda _cur, *_args, **_kwargs: next_id("artifact"),
            create_agent_run=lambda _cur, *_args, **_kwargs: next_id("run"),
            create_agent_message=lambda _cur, *args, **kwargs: scenario["agent_messages"].append((args, kwargs)) or next_id("message"),
            build_specialist_execution_request=lambda **kwargs: {
                "assigned_step_orders": [int(step.get("step_order") or 0) for step in kwargs.get("assigned_steps", []) if int(step.get("step_order") or 0) > 0],
                "evidence_refs": [],
                "slot": kwargs["slot"],
                "subtask_type": kwargs.get("subtask_type") or "readonly_step_digest",
                "source": kwargs.get("source"),
            },
            insert_audit_log=lambda _cur, event_type, actor, task_id, details: scenario["audit_logs"].append(
                (event_type, actor, task_id, details)
            ),
            logger=logger,
            safe_json_dumps=lambda value: value,
            serialize_agent_artifact_row=lambda row: {
                **dict(row),
                "id": row["id"],
                "artifact_type": row["artifact_type"],
                "version": row.get("version", 1),
            },
            build_specialist_step_partitions=lambda **kwargs: (
                [{"step_order": 1}],
                [[{"step_order": 1, "step_name": "collect"}] for _ in range(kwargs["specialist_count"])],
                {"completed": len(kwargs.get("step_rows", []))},
            ),
            build_specialist_draft_payload=lambda **kwargs: {"slot": kwargs["slot"], "task_id": kwargs["task_id"]},
            enqueue_agent_run=lambda run_id: scenario["enqueued_runs"].append(run_id),
            resolve_reviewer_decision=lambda **_kwargs: ("approved", "auto_rule"),
            build_demo_review_criteria=lambda **_kwargs: {"criteria": ["ok"], "score": 92, "step_stats": {"completed": 1}},
            derive_evaluator_failure_profile=lambda **_kwargs: {
                "failure_reason": "none",
                "failure_stage": "none",
                "summary": "ok",
                "recommendation": "complete",
            },
            build_workflow_proposal=lambda **kwargs: {"task_id": kwargs["task_id"], "action_key": "none"},
            create_evaluator_run=lambda _cur, **_kwargs: next_id("evaluator"),
            serialize_workflow_proposal=lambda **kwargs: {"proposal_id": kwargs["evaluator_run"]["id"], **kwargs["proposal"]},
        )
    )
    return TestClient(app), conn, logger


def test_multi_agent_demo_routes_bootstrap_success_and_conflict():
    scenario = {
        "bootstrap_task_row": {"id": 11, "user_input": "do work", "status": "queued", "runtime_overrides": {}},
        "agent_run_count": 0,
    }
    client, conn, logger = build_client(scenario)

    response = client.post(
        "/tasks/11/agent-runs/bootstrap-demo",
        headers={"X-Actor-Name": "local_admin"},
        json={"objective": "", "specialist_count": 2, "include_reviewer": True, "note": "boot"},
    )

    assert response.status_code == 200
    assert response.json()["created_agent_run_count"] == 4
    assert response.json()["created_artifact_count"] == 4
    assert conn.commit_called == 1
    assert "agent bootstrap demo created" in logger.messages[0]

    conflict_scenario = {
        "bootstrap_task_row": {"id": 11, "user_input": "do work", "status": "queued", "runtime_overrides": {}},
        "agent_run_count": 2,
    }
    conflict_client, _conn, _logger = build_client(conflict_scenario)
    conflict_response = conflict_client.post(
        "/tasks/11/agent-runs/bootstrap-demo",
        headers={"X-Actor-Name": "local_admin"},
        json={"objective": "", "specialist_count": 2, "include_reviewer": False, "note": "boot"},
    )
    assert conflict_response.status_code == 409


def test_multi_agent_demo_routes_execute_demo_and_worker_validation():
    scenario = {
        "task_row": {"id": 22, "user_input": "analyze", "status": "running", "runtime_overrides": {}},
        "agent_rows": [
            {"id": 1, "role": "manager", "status": "completed"},
            {"id": 2, "role": "specialist", "status": "queued", "attempt": 1, "brief_artifact_id": 10, "output_artifact_id": None},
        ],
        "step_rows": [{"step_order": 1, "step_name": "collect", "status": "completed"}],
        "artifact_rows": [{"id": 10, "artifact_type": "plan", "version": 1}],
    }
    client, conn, logger = build_client(scenario)

    execute_response = client.post(
        "/tasks/22/agent-runs/execute-demo",
        headers={"X-Actor-Name": "local_admin"},
        json={"note": "go", "force_rerun": False},
    )
    assert execute_response.status_code == 200
    assert execute_response.json()["executed_specialist_ids"] == [2]
    assert conn.commit_called == 1
    assert "agent execute demo completed" in logger.messages[0]

    invalid_worker_response = client.post(
        "/tasks/22/agent-runs/execute-worker-demo",
        headers={"X-Actor-Name": "local_admin"},
        json={"subtask_type": "bad_mode"},
    )
    assert invalid_worker_response.status_code == 400


def test_multi_agent_demo_routes_execute_worker_success():
    scenario = {
        "task_row": {"id": 33, "user_input": "snapshot", "status": "running", "runtime_overrides": {}},
        "agent_rows": [
            {"id": 1, "role": "manager", "status": "completed"},
            {"id": 2, "role": "specialist", "status": "queued", "brief_artifact_id": 10, "output_artifact_id": None},
        ],
        "step_rows": [{"step_order": 1, "step_name": "collect", "status": "completed"}],
        "artifact_rows": [{"id": 10, "artifact_type": "plan", "version": 1}],
    }
    client, conn, _logger = build_client(scenario)

    response = client.post(
        "/tasks/33/agent-runs/execute-worker-demo",
        headers={"X-Actor-Name": "local_admin"},
        json={"note": "queue", "subtask_type": "readonly_source_snapshot", "source_kind": "text_file", "source_path": "README.md"},
    )

    assert response.status_code == 200
    assert response.json()["execution_backend"] == "worker"
    assert response.json()["queued_specialist_ids"] == [2]
    assert scenario["enqueued_runs"] == [2]
    assert conn.commit_called == 1


def test_multi_agent_demo_routes_finalize_validation_and_success():
    invalid_scenario = {}
    invalid_client, _conn, _logger = build_client(invalid_scenario)
    invalid_response = invalid_client.post(
        "/tasks/44/agent-runs/finalize-demo",
        headers={"X-Actor-Name": "local_admin"},
        json={"reviewer_decision": "bad"},
    )
    assert invalid_response.status_code == 400

    scenario = {
        "task_row": {"id": 44, "user_input": "finalize", "status": "completed", "runtime_overrides": {}},
        "agent_rows": [
            {"id": 1, "role": "manager", "status": "completed"},
            {"id": 2, "role": "specialist", "status": "completed", "output_artifact_id": None, "brief_artifact_id": 10},
        ],
        "step_rows": [{"step_order": 1, "step_name": "collect", "status": "completed"}],
        "artifact_rows": [{"id": 10, "artifact_type": "plan", "version": 1}],
    }
    client, conn, logger = build_client(scenario)
    response = client.post(
        "/tasks/44/agent-runs/finalize-demo",
        headers={"X-Actor-Name": "local_admin"},
        json={"summary": "done", "reviewer_decision": "auto", "allow_retry": False},
    )

    assert response.status_code == 200
    assert response.json()["reviewer_decision"] == "approved"
    assert response.json()["evaluator_run_id"] > 0
    assert response.json()["workflow_proposal"]["proposal_id"] > 0
    assert conn.commit_called == 1
    assert "agent finalize demo completed" in logger.messages[0]
