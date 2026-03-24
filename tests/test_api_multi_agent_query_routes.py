from __future__ import annotations

from copy import deepcopy

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import multi_agent_query_routes


class MultiAgentQueryCursor:
    def __init__(self, scenario: dict):
        self.scenario = scenario
        self._fetchone = None
        self._fetchall = []

    def execute(self, sql, params=None):
        normalized = " ".join(str(sql).split())
        params = params or ()

        if "FROM agent_runs" in normalized and "ORDER BY id DESC;" in normalized:
            rows = deepcopy(self.scenario.get("agent_runs", []))
            task_id = int(params[0]) if "task_run_id = %s" in normalized else None
            role = params[1] if "role = %s" in normalized and len(params) > 1 else None
            status = params[-1] if "status = %s" in normalized else None
            if task_id is not None:
                rows = [row for row in rows if int(row["task_run_id"]) == task_id]
            if role:
                rows = [row for row in rows if row.get("role") == role]
            if status:
                rows = [row for row in rows if row.get("status") == status]
            self._fetchall = rows
            self._fetchone = None
            return

        if "SELECT id FROM task_runs WHERE id =" in normalized:
            task_id = int(params[0])
            exists_ids = set(self.scenario.get("existing_task_ids", []))
            self._fetchone = {"id": task_id} if task_id in exists_ids else None
            self._fetchall = []
            return

        if "FROM agent_runs" in normalized and "WHERE id = %s;" in normalized:
            agent_run_id = int(params[0])
            agent_run = next((row for row in self.scenario.get("agent_runs", []) if int(row["id"]) == agent_run_id), None)
            self._fetchone = deepcopy(agent_run)
            self._fetchall = []
            return

        if "FROM agent_messages" in normalized:
            agent_run_id = int(params[0])
            limit = int(params[1])
            rows = [row for row in self.scenario.get("agent_messages", []) if int(row["agent_run_id"]) == agent_run_id]
            self._fetchall = deepcopy(rows[:limit])
            self._fetchone = None
            return

        if "FROM agent_artifacts" in normalized:
            agent_run_id = int(params[0])
            referenced_ids = {int(item) for item in (params[1] or [])}
            limit = int(params[2])
            rows = [
                row
                for row in self.scenario.get("agent_artifacts", [])
                if int(row["agent_run_id"]) == agent_run_id or int(row["id"]) in referenced_ids
            ]
            self._fetchall = deepcopy(rows[:limit])
            self._fetchone = None
            return

        if "FROM evaluator_runs" in normalized and "ORDER BY id DESC LIMIT %s;" in normalized:
            rows = deepcopy(self.scenario.get("evaluator_runs", []))
            if "WHERE task_run_id = %s" in normalized:
                task_id = int(params[0])
                limit = int(params[1])
                rows = [row for row in rows if int(row["task_run_id"]) == task_id]
            else:
                limit = int(params[0])
            self._fetchall = rows[:limit]
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


class MultiAgentQueryConn:
    def __init__(self, cursor: MultiAgentQueryCursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def close(self):
        return None


def build_client(scenario: dict):
    cursor = MultiAgentQueryCursor(scenario)
    conn = MultiAgentQueryConn(cursor)
    scenario["permission_checks"] = []

    def require_actor_permission(_cur, actor_name, permission):
        scenario["permission_checks"].append((actor_name or "local_admin", permission))
        return {"actor_name": actor_name or "local_admin", "role": "admin"}

    def fetch_task_agent_summary(_cur, task_id: int):
        summaries = scenario.get("task_summaries", {})
        if task_id not in summaries:
            raise AssertionError(f"missing summary for task {task_id}")
        return deepcopy(summaries[task_id])

    def serialize_workflow_proposal(*, evaluator_run, proposal=None):
        body = deepcopy(proposal or evaluator_run.get("workflow_proposal") or {})
        return {
            "proposal_id": int(evaluator_run["id"]),
            "task_id": int(evaluator_run["task_run_id"]),
            **body,
        }

    def get_workflow_proposal_or_404(_cur, proposal_id: int, **_kwargs):
        proposal = scenario.get("workflow_proposals", {}).get(proposal_id)
        if not proposal:
            raise HTTPException(status_code=404, detail="Workflow proposal not found")
        return deepcopy(proposal)

    def build_workflow_proposal_shadow_status(_cur, *, workflow_proposal, proposal_id, history_limit, build_workflow_proposal_shadow_validation_status_fn):
        return {
            "history_limit": history_limit,
            "shadow_status": build_workflow_proposal_shadow_validation_status_fn(
                _cur,
                workflow_proposal=workflow_proposal,
                proposal_id=proposal_id,
                history_limit=history_limit,
            ),
        }

    def get_workflow_proposal_change_request_draft_response(
        _cur,
        *,
        workflow_proposal,
        suggest_change_request_draft_from_workflow_proposal_fn,
        attach_patch_artifacts_to_change_request_draft_fn,
        attach_shadow_validation_state_to_change_request_draft_fn,
    ):
        draft = suggest_change_request_draft_from_workflow_proposal_fn(_cur, workflow_proposal)
        draft = attach_patch_artifacts_to_change_request_draft_fn(_cur, draft)
        draft = attach_shadow_validation_state_to_change_request_draft_fn(_cur, draft)
        return draft

    app = FastAPI()
    app.include_router(
        multi_agent_query_routes.register_multi_agent_query_routes(
            get_conn=lambda: conn,
            require_actor_permission=require_actor_permission,
            serialize_agent_run_row=lambda row: {
                **dict(row),
                "assigned_step_orders": deepcopy(row.get("assigned_step_orders_json", [])),
                "execution_request": deepcopy(row.get("execution_request_json") or {}),
            },
            serialize_agent_message_row=lambda row: {
                **dict(row),
                "payload": deepcopy(row.get("payload_json") or {}),
            },
            serialize_agent_artifact_row=lambda row: {
                **dict(row),
                "content": deepcopy(row.get("content_json") or {}),
            },
            fetch_task_agent_summary=fetch_task_agent_summary,
            serialize_evaluator_run_row=lambda row: {
                **dict(row),
                "workflow_proposal": deepcopy(row.get("proposal_json") or {}),
            },
            serialize_workflow_proposal=serialize_workflow_proposal,
            fetch_latest_evaluator_for_task=lambda _cur, task_id: deepcopy(scenario.get("latest_evaluators", {}).get(task_id)),
            list_workflow_proposals_rows=lambda _cur, **kwargs: deepcopy(scenario.get("workflow_proposal_lists", {}).get(kwargs.get("task_id"), scenario.get("workflow_proposal_lists", {}).get("all", []))),
            task_exists=lambda _cur, task_id: int(task_id) in set(scenario.get("existing_task_ids", [])),
            get_workflow_proposal_or_404=get_workflow_proposal_or_404,
            build_workflow_proposal_shadow_validation_response=lambda _cur, **kwargs: {
                "workflow_proposal": deepcopy(kwargs["workflow_proposal"]),
                **kwargs["build_workflow_proposal_shadow_status_fn"](
                    _cur,
                    workflow_proposal=kwargs["workflow_proposal"],
                    proposal_id=kwargs["proposal_id"],
                    history_limit=kwargs["history_limit"],
                ),
            },
            build_workflow_proposal_shadow_status=build_workflow_proposal_shadow_status,
            build_workflow_proposal_shadow_validation_status_with_context=lambda _cur, **kwargs: {
                "proposal_id": kwargs["proposal_id"],
                "matched": True,
                "history_limit": kwargs["history_limit"],
            },
            get_workflow_proposal_change_request_draft_response=get_workflow_proposal_change_request_draft_response,
            suggest_change_request_draft_from_workflow_proposal_with_context=lambda _cur, workflow_proposal: {
                "title": workflow_proposal.get("title"),
                "action_key": workflow_proposal.get("action_key"),
            },
            attach_patch_artifacts_to_change_request_draft_with_context=lambda _cur, draft: {
                **draft,
                "patch_artifacts": [{"artifact_id": 301}],
            },
            attach_shadow_validation_state_to_change_request_draft_with_context=lambda _cur, draft: {
                **draft,
                "shadow_validation": {"status": "ready"},
            },
            fetch_evaluator_run_row=lambda _cur, evaluator_run_id: deepcopy(scenario.get("evaluator_rows_by_id", {}).get(evaluator_run_id)),
            get_evaluator_run_or_404=lambda _cur, evaluator_run_id, **kwargs: (
                kwargs["serialize_evaluator_run_row_fn"](kwargs["fetch_evaluator_run_row_fn"](_cur, evaluator_run_id))
                if kwargs["fetch_evaluator_run_row_fn"](_cur, evaluator_run_id)
                else (_ for _ in ()).throw(HTTPException(status_code=404, detail="Evaluator run not found"))
            ),
        )
    )
    return TestClient(app)


def test_multi_agent_query_routes_agent_runs_and_messages():
    scenario = {
        "agent_runs": [
            {
                "id": 11,
                "task_run_id": 21,
                "role": "specialist",
                "status": "completed",
                "assigned_step_orders_json": [2, 3],
                "execution_request_json": {"subtask_type": "readonly_step_digest"},
                "brief_artifact_id": 1001,
                "output_artifact_id": 1002,
                "review_artifact_id": 1003,
            }
        ],
        "agent_messages": [
            {"id": 501, "agent_run_id": 11, "task_run_id": 21, "payload_json": {"text": "done"}},
            {"id": 502, "agent_run_id": 11, "task_run_id": 21, "payload_json": {"text": "older"}},
        ],
    }
    client = build_client(scenario)

    list_response = client.get(
        "/agent-runs?task_id=21&role=specialist&status=completed",
        headers={"X-Actor-Name": "local_admin"},
    )
    message_response = client.get("/agent-runs/11/messages?limit=1", headers={"X-Actor-Name": "local_admin"})

    assert list_response.status_code == 200
    assert list_response.json()[0]["assigned_step_orders"] == [2, 3]
    assert message_response.status_code == 200
    assert message_response.json()[0]["payload"]["text"] == "done"


def test_multi_agent_query_routes_task_summary_and_artifacts():
    scenario = {
        "existing_task_ids": [21],
        "task_summaries": {
            21: {"task_id": 21, "recommended_action": "execute", "role_counts": {"specialist": 2}}
        },
        "agent_runs": [
            {
                "id": 11,
                "task_run_id": 21,
                "role": "manager",
                "status": "running",
                "brief_artifact_id": 1001,
                "output_artifact_id": 1002,
                "review_artifact_id": 1003,
            }
        ],
        "agent_artifacts": [
            {"id": 1001, "agent_run_id": 0, "task_run_id": 21, "artifact_type": "brief", "content_json": {"v": 1}},
            {"id": 1002, "agent_run_id": 11, "task_run_id": 21, "artifact_type": "final", "content_json": {"v": 2}},
        ],
    }
    client = build_client(scenario)

    summary_response = client.get("/tasks/21/agent-runs/summary", headers={"X-Actor-Name": "local_admin"})
    artifacts_response = client.get("/agent-runs/11/artifacts", headers={"X-Actor-Name": "local_admin"})
    missing_response = client.get("/tasks/999/agent-runs/summary", headers={"X-Actor-Name": "local_admin"})

    assert summary_response.status_code == 200
    assert summary_response.json()["recommended_action"] == "execute"
    assert artifacts_response.status_code == 200
    assert {item["id"] for item in artifacts_response.json()} == {1001, 1002}
    assert missing_response.status_code == 404


def test_multi_agent_query_routes_evaluator_and_workflow_queries():
    scenario = {
        "existing_task_ids": [21],
        "evaluator_runs": [
            {"id": 801, "task_run_id": 21, "proposal_json": {"action_key": "model_route_patch", "priority": "high"}}
        ],
        "latest_evaluators": {
            21: {"id": 801, "task_run_id": 21, "workflow_proposal": {"action_key": "model_route_patch", "priority": "high"}}
        },
        "workflow_proposal_lists": {
            "all": [{"proposal_id": 801, "task_id": 21, "action_key": "model_route_patch", "priority": "high"}],
            21: [{"proposal_id": 801, "task_id": 21, "action_key": "model_route_patch", "priority": "high"}],
        },
        "evaluator_rows_by_id": {
            801: {"id": 801, "task_run_id": 21, "proposal_json": {"action_key": "model_route_patch"}}
        },
    }
    client = build_client(scenario)

    evaluator_response = client.get("/evaluator-runs?task_id=21&limit=5", headers={"X-Actor-Name": "local_admin"})
    latest_response = client.get("/tasks/21/evaluator-runs/latest", headers={"X-Actor-Name": "local_admin"})
    proposal_response = client.get("/tasks/21/workflow-proposals/latest", headers={"X-Actor-Name": "local_admin"})
    list_response = client.get("/workflow-proposals", headers={"X-Actor-Name": "local_admin"})
    detail_response = client.get("/evaluator-runs/801", headers={"X-Actor-Name": "local_admin"})

    assert evaluator_response.status_code == 200
    assert evaluator_response.json()[0]["workflow_proposal"]["action_key"] == "model_route_patch"
    assert latest_response.status_code == 200
    assert latest_response.json()["id"] == 801
    assert proposal_response.status_code == 200
    assert proposal_response.json()["priority"] == "high"
    assert list_response.status_code == 200
    assert list_response.json()[0]["proposal_id"] == 801
    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == 801


def test_multi_agent_query_routes_workflow_proposal_shadow_and_draft():
    scenario = {
        "workflow_proposals": {
            901: {"proposal_id": 901, "task_id": 21, "title": "Promote route", "action_key": "model_route_patch"}
        }
    }
    client = build_client(scenario)

    shadow_response = client.get(
        "/workflow-proposals/901/shadow-validation?history_limit=7",
        headers={"X-Actor-Name": "local_admin"},
    )
    draft_response = client.get(
        "/workflow-proposals/901/change-request-draft",
        headers={"X-Actor-Name": "local_admin"},
    )

    assert shadow_response.status_code == 200
    assert shadow_response.json()["shadow_status"]["proposal_id"] == 901
    assert shadow_response.json()["history_limit"] == 7
    assert draft_response.status_code == 200
    assert draft_response.json()["patch_artifacts"][0]["artifact_id"] == 301
    assert draft_response.json()["shadow_validation"]["status"] == "ready"
