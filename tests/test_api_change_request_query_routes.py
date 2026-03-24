from __future__ import annotations

from copy import deepcopy

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import change_request_query_routes


class ChangeRequestQueryCursor:
    def __init__(self, scenario: dict):
        self.scenario = scenario
        self._fetchone = None
        self._fetchall = []

    def execute(self, sql, params=None):
        normalized = " ".join(str(sql).split())
        params = params or ()

        if "FROM change_requests" in normalized and "ORDER BY id DESC LIMIT %s OFFSET %s;" in normalized:
            rows = deepcopy(self.scenario.get("change_request_rows", []))
            if "status = %s" in normalized:
                rows = [row for row in rows if row.get("status") == params[0]]
            self._fetchall = rows
            self._fetchone = None
            return

        self._fetchall = []
        self._fetchone = None

    def fetchone(self):
        return deepcopy(self._fetchone)

    def fetchall(self):
        return deepcopy(self._fetchall)

    def close(self):
        return None


class ChangeRequestQueryConn:
    def __init__(self, cursor: ChangeRequestQueryCursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def close(self):
        return None


def build_client(scenario: dict):
    cursor = ChangeRequestQueryCursor(scenario)
    conn = ChangeRequestQueryConn(cursor)
    scenario["permission_checks"] = []

    def require_actor_permission(_cur, actor_name, permission):
        scenario["permission_checks"].append((actor_name or "local_admin", permission))
        return {"actor_name": actor_name or "local_admin", "role": "admin"}

    def get_change_request_or_404(_cur, _ensure_table, change_request_id):
        row = scenario.get("change_request_by_id", {}).get(change_request_id)
        if not row:
            raise HTTPException(status_code=404, detail="Change request not found")
        return {**deepcopy(row), "serialized_mode": "full"}

    app = FastAPI()
    app.include_router(
        change_request_query_routes.register_change_request_query_routes(
            get_conn=lambda: conn,
            require_actor_permission=require_actor_permission,
            ensure_change_requests_table=lambda _cur: None,
            normalize_change_request_proposal_kind=lambda value: (value or "").strip().lower() or "manual_change",
            change_request_select_fields="id, status, target_type, target_key, proposal_kind, proposed_payload",
            serialize_change_request_row=lambda row: {**dict(row), "serialized_mode": "full"},
            serialize_change_request_list_row=lambda row: {
                "id": row["id"],
                "status": row["status"],
                "target_type": row["target_type"],
                "serialized_mode": "list",
            },
            get_change_request_or_404=get_change_request_or_404,
            collect_change_request_shadow_validation_context=lambda **kwargs: {
                "proposal_shadow_validation": {
                    "status": "completed",
                    "supported": True,
                    "history_count": kwargs["history_limit"],
                    "request_count": 1,
                    "validation_count": 1,
                    "latest_request": {"proposal_id": 501},
                    "history": [{"proposal_id": 501}],
                },
                "latest_matching_validation": {"audit_log_id": 701, "validation": {"shadow_task_id": 902}},
                "latest_proposal_validation": {"audit_log_id": 701},
                "latest_shadow_task": {"id": 902, "status": "completed"},
            },
            parse_optional_int=lambda value: int(value) if value not in (None, "") else None,
            build_workflow_proposal_shadow_validation_status_with_context=lambda _cur, proposal_id, **kwargs: {
                "proposal_id": proposal_id,
                **kwargs,
            },
            fetch_latest_workflow_proposal_shadow_validation_with_context=lambda _cur, proposal_id, **kwargs: {
                "proposal_id": proposal_id,
                **kwargs,
            },
            fetch_task_run_brief_with_context=lambda _cur, task_id: {"id": task_id, "status": "completed"} if task_id else None,
            build_change_request_shadow_validation_response=lambda **kwargs: {
                "change_request": {"id": kwargs["change_request"]["id"]},
                "proposal_shadow_validation_status": kwargs["proposal_shadow_validation"]["status"],
                "history_count": kwargs["proposal_shadow_validation"]["history_count"],
                "latest_shadow_task": kwargs["latest_shadow_task"],
            },
            prepare_change_request_rollback_context=lambda **kwargs: {
                "change_request": kwargs["get_change_request_fn"](kwargs["change_request_id"]),
                "draft": kwargs["build_change_request_rollback_draft_fn"](
                    kwargs["get_change_request_fn"](kwargs["change_request_id"])
                ),
                "existing_rollback_change_request": kwargs["find_open_rollback_change_request_fn"](kwargs["change_request_id"]),
            },
            build_change_request_rollback_draft=lambda change_request: {
                "target_type": change_request["target_type"],
                "target_key": change_request["target_key"],
                "rollback_ready": True,
                "rollback_note": "",
            },
            find_open_rollback_change_request=lambda _cur, change_request_id, _ensure_table: deepcopy(
                scenario.get("existing_rollback_by_source", {}).get(change_request_id)
            ),
            attach_patch_artifacts_to_change_request_draft_with_context=lambda _cur, draft: {
                **draft,
                "patch_artifacts": [{"artifact_id": 301}],
            },
            attach_shadow_validation_state_to_change_request_draft_with_context=lambda _cur, draft: {
                **draft,
                "shadow_validation": {"status": "ready"},
            },
        )
    )
    return TestClient(app)


def test_change_request_query_routes_list_and_detail():
    scenario = {
        "change_request_rows": [
            {"id": 1, "status": "approved", "target_type": "tool_registry", "target_key": "web_search", "proposal_kind": "manual_change", "proposed_payload": {"enabled": True}}
        ],
        "change_request_by_id": {
            1: {"id": 1, "status": "approved", "target_type": "tool_registry", "target_key": "web_search", "proposal_kind": "manual_change", "proposed_payload": {"enabled": True}}
        },
    }
    client = build_client(scenario)

    list_response = client.get("/change-requests?status=approved", headers={"X-Actor-Name": "local_admin"})
    detail_response = client.get("/change-requests/1", headers={"X-Actor-Name": "local_admin"})

    assert list_response.status_code == 200
    assert list_response.json()[0]["serialized_mode"] == "list"
    assert detail_response.status_code == 200
    assert detail_response.json()["serialized_mode"] == "full"


def test_change_request_query_routes_include_payloads():
    scenario = {
        "change_request_rows": [
            {"id": 2, "status": "pending", "target_type": "model_route", "target_key": "planner", "proposal_kind": "workflow_proposal", "proposed_payload": {"model_name": "gpt-5"}}
        ],
        "change_request_by_id": {},
    }
    client = build_client(scenario)

    response = client.get("/change-requests?include_payloads=true", headers={"X-Actor-Name": "local_admin"})

    assert response.status_code == 200
    assert response.json()[0]["serialized_mode"] == "full"


def test_change_request_query_routes_shadow_validation_summary():
    scenario = {
        "change_request_by_id": {
            7: {
                "id": 7,
                "status": "approved",
                "target_type": "tool_registry",
                "target_key": "web_search",
                "proposal_kind": "workflow_proposal",
                "source_workflow_proposal_id": 501,
                "requires_shadow_validation": True,
                "shadow_validation_status": "completed",
                "shadow_validation_ready_to_apply": True,
                "shadow_validation_report": {"audit_log_id": 701},
            }
        }
    }
    client = build_client(scenario)

    response = client.get("/change-requests/7/shadow-validation?history_limit=6", headers={"X-Actor-Name": "local_admin"})

    assert response.status_code == 200
    assert response.json()["proposal_shadow_validation_status"] == "completed"
    assert response.json()["history_count"] == 6
    assert response.json()["latest_shadow_task"]["id"] == 902


def test_change_request_query_routes_rollback_draft_includes_existing_request():
    scenario = {
        "change_request_by_id": {
            9: {
                "id": 9,
                "status": "applied",
                "target_type": "tool_registry",
                "target_key": "web_search",
            }
        },
        "existing_rollback_by_source": {
            9: {
                "id": 19,
                "status": "pending",
                "target_type": "tool_registry",
                "target_key": "web_search",
            }
        },
    }
    client = build_client(scenario)

    response = client.get("/change-requests/9/rollback-draft", headers={"X-Actor-Name": "local_admin"})

    assert response.status_code == 200
    assert response.json()["patch_artifacts"][0]["artifact_id"] == 301
    assert response.json()["shadow_validation"]["status"] == "ready"
    assert response.json()["existing_rollback_change_request"]["id"] == 19
