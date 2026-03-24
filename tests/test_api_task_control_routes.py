from __future__ import annotations

import json
from copy import deepcopy

from fastapi import FastAPI
from fastapi.testclient import TestClient

import task_control_routes


class TaskControlFakeCursor:
    def __init__(self, scenario: dict):
        self.scenario = scenario
        self.executed: list[tuple[str, tuple | None]] = []
        self._fetchone = None
        self._fetchall = []

    def execute(self, sql, params=None):
        normalized = " ".join(str(sql).split())
        self.executed.append((normalized, params))

        if "SELECT recovery_action_json FROM task_runs" in normalized:
            self._fetchone = {"recovery_action_json": self.scenario.get("recovery_action_json")}
            return

        if "SELECT step_order FROM task_steps" in normalized and "tool_name = 'generate_text'" in normalized:
            self._fetchone = {"step_order": self.scenario.get("generate_step_order", 2)}
            return

        if "SELECT id, status, current_step, checkpoint_path, error_message, user_input, runtime_overrides, recovery_action_json FROM task_runs" in normalized:
            self._fetchone = deepcopy(self.scenario.get("clarify_task"))
            return

        if "SELECT id FROM task_runs WHERE id =" in normalized:
            self._fetchone = {"id": int(params[0])} if self.scenario.get("task_exists", True) else None
            return

        if "FROM approvals WHERE task_id =" in normalized and "SELECT id FROM approvals" in normalized:
            self._fetchall = deepcopy(self.scenario.get("pending_approvals", []))
            return

        if "FROM approvals WHERE task_id =" in normalized and "step_name" in normalized:
            self._fetchall = deepcopy(self.scenario.get("approval_rows", []))
            return

        if "FROM approvals ORDER BY id DESC" in normalized:
            self._fetchall = deepcopy(self.scenario.get("all_approval_rows", []))
            return

        if "FROM approvals WHERE status =" in normalized and "ORDER BY id DESC" in normalized:
            requested_status = params[0]
            rows = [
                row for row in deepcopy(self.scenario.get("all_approval_rows", [])) if row.get("status") == requested_status
            ]
            self._fetchall = rows
            return

        if "SELECT id, task_id, step_order, status FROM approvals" in normalized:
            self._fetchone = deepcopy(self.scenario.get("approval"))
            return

        self._fetchone = None
        self._fetchall = []

    def fetchone(self):
        return deepcopy(self._fetchone)

    def fetchall(self):
        return deepcopy(self._fetchall)

    def close(self):
        return None


class TaskControlFakeConn:
    def __init__(self, cursor: TaskControlFakeCursor):
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


def build_test_client(scenario: dict):
    cursor = TaskControlFakeCursor(scenario)
    conn = TaskControlFakeConn(cursor)
    logger = FakeLogger()
    scenario["checkpoint_updates"] = []
    scenario["audit_logs"] = []
    scenario["resume_resets"] = []
    scenario["clarify_resets"] = []
    scenario["enqueued"] = []

    app = FastAPI()
    app.include_router(
        task_control_routes.register_task_control_routes(
            get_conn=lambda: conn,
            require_actor_permission=lambda _cur, actor_name, permission: {
                "actor_name": actor_name or "local_admin",
                "role": "admin",
                "permission": permission,
            },
            get_task_or_404=lambda _cur, task_id: deepcopy(scenario["task"])
            if int(scenario["task"]["id"]) == int(task_id)
            else (_ for _ in ()).throw(RuntimeError("unexpected task id")),
            update_checkpoint_status=lambda checkpoint_path, status, note: scenario["checkpoint_updates"].append(
                (checkpoint_path, status, note)
            ),
            insert_audit_log=lambda _cur, event_type, actor_name, task_id, payload: scenario["audit_logs"].append(
                (event_type, actor_name, task_id, payload)
            ),
            resolve_resume_from_step=lambda _cur, _task_id, from_step: int(from_step or 1),
            reset_task_for_resume=lambda _cur, **kwargs: scenario["resume_resets"].append(kwargs),
            reset_task_for_clarification=lambda _cur, **kwargs: scenario["clarify_resets"].append(kwargs),
            enqueue_task=lambda task_id: scenario["enqueued"].append(task_id),
            parse_maybe_json=lambda value: json.loads(value) if isinstance(value, str) else value,
            extract_task_clarification_state=lambda runtime_overrides, fallback_user_input: (
                runtime_overrides.get("clarification_state", {}).get("original_user_input") or fallback_user_input,
                list(runtime_overrides.get("clarification_state", {}).get("history") or []),
            ),
            build_clarified_user_input=lambda original_input, history: original_input
            + "\n"
            + "\n".join(item["clarification"] for item in history),
            infer_task_intent=lambda user_input, skill_id=None: {
                "task_type": "research",
                "skill_id": skill_id,
                "goal_summary": user_input[:80],
            },
            build_task_display_user_input=lambda user_input, _overrides: user_input,
            infer_deliverable_spec=lambda _user_input, task_intent: {
                "deliverable_type": "research_summary",
                "task_type": task_intent.get("task_type"),
            },
            logger=logger,
        )
    )
    return TestClient(app), conn, logger


def test_interrupt_task_route_updates_status_checkpoint_and_audit():
    scenario = {
        "task": {"id": 77, "status": "running", "checkpoint_path": "/tmp/task-77.json"},
    }
    client, conn, logger = build_test_client(scenario)

    response = client.post("/tasks/77/interrupt", headers={"X-Actor-Name": "local_admin"}, json={"note": "pause now"})

    assert response.status_code == 200
    assert response.json()["status"] == "interrupt_requested"
    assert conn.commit_called == 1
    assert scenario["checkpoint_updates"] == [("/tmp/task-77.json", "running", "pause now")]
    assert scenario["audit_logs"][0][0] == "task.interrupt"
    assert "task interrupt requested" in logger.messages[0]


def test_apply_recovery_action_route_resolves_retry_generate_step_and_enqueues_task():
    scenario = {
        "task": {"id": 88, "status": "failed", "current_step": 5, "checkpoint_path": "/tmp/task-88.json"},
        "recovery_action_json": json.dumps({"action": "retry_generate"}),
        "pending_approvals": [],
        "generate_step_order": 2,
    }
    client, conn, logger = build_test_client(scenario)

    response = client.post(
        "/tasks/88/apply-recovery-action",
        headers={"X-Actor-Name": "local_admin"},
        json={"note": "", "from_step": None},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "retry_generate"
    assert payload["from_step"] == 2
    assert conn.commit_called == 1
    assert scenario["resume_resets"][0]["resume_from"] == 2
    assert scenario["resume_resets"][0]["event_type"] == "task.apply_recovery_action"
    assert scenario["enqueued"] == [88]
    assert "action=retry_generate" in logger.messages[0]


def test_clarify_task_route_rebuilds_input_and_requeues_task():
    scenario = {
        "task": {"id": 66, "status": "failed", "current_step": 2, "checkpoint_path": "/tmp/task-66.json"},
        "clarify_task": {
            "id": 66,
            "status": "failed",
            "current_step": 2,
            "checkpoint_path": "/tmp/task-66.json",
            "error_message": "need clarify",
            "user_input": "原始任务",
            "runtime_overrides": json.dumps(
                {
                    "skill_invocation": {"skill_id": "demo_skill"},
                    "clarification_state": {
                        "original_user_input": "原始任务",
                        "history": [{"clarification": "旧信息", "note": "old"}],
                    },
                }
            ),
            "recovery_action_json": json.dumps({"action": "clarify"}),
        },
        "pending_approvals": [],
    }
    client, conn, logger = build_test_client(scenario)

    response = client.post(
        "/tasks/66/clarify",
        headers={"X-Actor-Name": "local_admin"},
        json={"clarification": "补充条件", "note": "请重试"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "clarify"
    assert payload["from_step"] == 1
    assert conn.commit_called == 1
    clarify_reset = scenario["clarify_resets"][0]
    assert "补充条件" in clarify_reset["new_user_input"]
    assert clarify_reset["details"]["clarification_count"] == 2
    assert scenario["enqueued"] == [66]
    assert "task clarified" in logger.messages[0]


def test_list_task_approvals_returns_rows_from_dedicated_route():
    scenario = {
        "task": {"id": 66, "status": "paused", "checkpoint_path": "/tmp/task-66.json"},
        "task_exists": True,
        "approval_rows": [
            {
                "id": 901,
                "task_id": 66,
                "step_order": 3,
                "step_name": "生成文案",
                "tool_name": "generate_text",
                "input_payload": {"prompt": "生成文案"},
                "reason": "需要人工确认",
                "status": "pending",
                "decision_note": "",
                "created_at": "2026-03-24T00:00:00+00:00",
                "updated_at": "2026-03-24T00:00:00+00:00",
                "decided_at": None,
            }
        ],
    }
    client, _conn, _logger = build_test_client(scenario)

    response = client.get("/tasks/66/approvals", headers={"X-Actor-Name": "local_admin"})

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["step_name"] == "生成文案"


def test_list_approvals_route_filters_by_status():
    scenario = {
        "task": {"id": 66, "status": "waiting_approval", "checkpoint_path": "/tmp/task-66.json"},
        "all_approval_rows": [
            {"id": 1, "task_id": 66, "step_order": 1, "status": "pending"},
            {"id": 2, "task_id": 77, "step_order": 2, "status": "approved"},
        ],
    }
    client, _conn, _logger = build_test_client(scenario)

    response = client.get("/approvals?status=pending", headers={"X-Actor-Name": "local_admin"})

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"


def test_approve_approval_route_updates_task_and_enqueues():
    scenario = {
        "task": {"id": 66, "status": "waiting_approval", "checkpoint_path": "/tmp/task-66.json"},
        "approval": {"id": 301, "task_id": 66, "step_order": 2, "status": "pending"},
    }
    client, conn, logger = build_test_client(scenario)

    response = client.post(
        "/approvals/301/approve",
        headers={"X-Actor-Name": "local_admin"},
        json={"note": "可以继续"},
    )

    assert response.status_code == 200
    assert response.json()["approval_id"] == 301
    assert conn.commit_called == 1
    assert scenario["enqueued"] == [66]
    assert scenario["audit_logs"][0][0] == "approval.approve"
    assert "approval approved" in logger.messages[0]
