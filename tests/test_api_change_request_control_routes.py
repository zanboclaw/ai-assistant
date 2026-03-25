from __future__ import annotations

from copy import deepcopy

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import change_request_control_routes


class ControlCursor:
    def close(self):
        return None


class ControlConn:
    def __init__(self):
        self._cursor = ControlCursor()
        self.commit_called = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commit_called += 1

    def close(self):
        return None


def build_client(scenario: dict, require_actor_permission=None):
    conn = ControlConn()
    scenario["audit_logs"] = []
    scenario["audit_events"] = []
    scenario["permission_checks"] = []

    def default_require_actor_permission(_cur, actor_name, permission):
        scenario["permission_checks"].append((actor_name or "local_admin", permission))
        return {"actor_name": actor_name or "local_admin", "role": "admin"}

    def get_change_request_or_404(_cur, _ensure_table, change_request_id):
        row = scenario.get("change_requests", {}).get(change_request_id)
        if not row:
            raise HTTPException(status_code=404, detail="Change request not found")
        return deepcopy(row)

    def get_workflow_proposal_or_404(_cur, proposal_id, **_kwargs):
        proposal = scenario.get("workflow_proposals", {}).get(proposal_id)
        if not proposal:
            raise HTTPException(status_code=404, detail="Workflow proposal not found")
        return deepcopy(proposal)

    app = FastAPI()
    app.include_router(
        change_request_control_routes.register_change_request_control_routes(
            get_conn=lambda: conn,
            require_actor_permission=require_actor_permission or default_require_actor_permission,
            supported_change_target_types={"tool_registry", "model_route"},
            create_change_request_with_audit=lambda **kwargs: {
                "id": 101,
                "target_type": kwargs["target_type"],
                "target_key": kwargs["target_key"],
                "patch_summary": "created",
            },
            create_change_request_row=lambda _cur, **kwargs: {
                "id": scenario.get("created_row_id", 301),
                **kwargs,
                "patch_summary": "rollback-created",
            },
            serialize_change_request_row=lambda row: {**dict(row), "serialized": True, "patch_summary": row.get("patch_summary", "summary")},
            insert_audit_log=lambda _cur, event_type, actor, task_id, details: scenario["audit_logs"].append(
                (event_type, actor, task_id, details)
            ),
            ensure_change_requests_table=lambda _cur: None,
            get_change_request_or_404=get_change_request_or_404,
            review_change_request=lambda **kwargs: {
                "id": kwargs["change_request_id"],
                "status": kwargs["next_status"],
                "note": kwargs["note"],
            },
            update_reviewed_change_request_row=lambda _cur, **kwargs: kwargs,
            execute_change_request_apply=lambda **kwargs: {
                "id": kwargs["change_request_id"],
                "status": "applied",
                "target_type": kwargs["change_request"]["target_type"],
            },
            normalize_change_request_payload=lambda target_type, payload: {"target_type": target_type, **payload},
            fetch_change_target_state_for_rollback_with_context=lambda _cur, **kwargs: {"baseline": kwargs["target_key"]},
            apply_change_request_payload_with_context=lambda _cur, target_type, target_key, payload: scenario.setdefault(
                "applied_payloads", []
            ).append((target_type, target_key, payload)),
            process_change_request_post_apply_with_context=lambda _cur, **kwargs: {
                "acceptance_status": "passed",
                "acceptance_report": {"ok": True},
                "acceptance_at": "now",
                "auto_rollback_change_request_id": None,
                "auto_rollback_at": None,
            },
            safe_json_dumps=lambda value: value,
            update_applied_change_request_row=lambda _cur, **kwargs: {"id": kwargs["change_request_id"], **kwargs, "patch_summary": "applied"},
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
                "proposed_payload": {"enabled": False},
                "rationale": "rollback",
                "rollback_ready": scenario.get("rollback_ready", True),
                "rollback_note": scenario.get("rollback_note", ""),
            },
            find_open_rollback_change_request=lambda _cur, change_request_id, _ensure_table: deepcopy(
                scenario.get("existing_rollbacks", {}).get(change_request_id)
            ),
            get_workflow_proposal_or_404=get_workflow_proposal_or_404,
            serialize_evaluator_run_row=lambda row: dict(row),
            serialize_workflow_proposal=lambda **kwargs: dict(kwargs["evaluator_run"]),
            create_change_request_from_workflow_proposal_draft=lambda _cur, **kwargs: (
                kwargs["require_actor_permission_fn"](_cur, kwargs["x_actor_name"], "operate"),
                {
                    "change_request": {"id": 202, "target_type": kwargs["request"].target_type},
                    "workflow_proposal": kwargs["workflow_proposal"],
                },
            )[1],
            build_change_request_draft_from_workflow_proposal=lambda **kwargs: kwargs,
            record_audit_event=lambda event_type, actor, task_id, details: scenario["audit_events"].append(
                (event_type, actor, task_id, details)
            ),
            launch_workflow_proposal_shadow_validation=lambda _cur, **kwargs: (
                kwargs["require_actor_permission_fn"](_cur, kwargs["x_actor_name"], "operate"),
                {
                    "shadow_context": {"execution_payload": {"validation_request": {"mode": "shadow"}}},
                    "shadow_task": {"id": 909},
                },
            )[1],
            enforce_task_quota=lambda *_args, **_kwargs: None,
            prepare_shadow_validation_baseline=lambda *_args, **_kwargs: None,
            resolve_shadow_validation_candidate_overlay_with_context=lambda *_args, **_kwargs: {"candidate": True},
            build_shadow_validation_runtime_overrides=lambda **_kwargs: {"shadow_validation": True},
            build_shadow_validation_execution_payload_with_context=lambda **_kwargs: {"payload": True},
            parse_optional_int=lambda value: int(value) if value not in (None, "") else None,
            complete_workflow_proposal_shadow_validation=lambda **kwargs: {
                "workflow_proposal": kwargs["workflow_proposal"],
                "shadow_task": kwargs["shadow_task"],
            },
            enqueue_task=lambda task_id: scenario.setdefault("enqueued_tasks", []).append(task_id),
            finalize_shadow_validation_response_with_context=lambda **kwargs: kwargs,
            resolve_change_request_shadow_validation_target=lambda _cur, **kwargs: (
                kwargs["require_actor_permission_fn"](_cur, kwargs["x_actor_name"], "operate"),
                {
                    "change_request": {"id": kwargs["change_request_id"], "target_type": "tool_registry"},
                    "workflow_proposal": {"id": 501, "task_run_id": 77},
                },
            )[1],
            ensure_change_request_shadow_validation_eligible=lambda *_args, **_kwargs: 501,
        )
    )
    return TestClient(app), conn


def test_change_request_control_routes_create_and_review():
    scenario = {
        "change_requests": {
            11: {"id": 11, "status": "pending", "target_type": "tool_registry", "target_key": "web_search"}
        }
    }
    client, conn = build_client(scenario)

    create_response = client.post(
        "/change-requests",
        headers={"X-Actor-Name": "local_admin"},
        json={"target_type": "tool_registry", "target_key": "web_search", "proposed_payload": {"enabled": True}, "rationale": "open"},
    )
    approve_response = client.post(
        "/change-requests/11/approve",
        headers={"X-Actor-Name": "local_admin"},
        json={"note": "ok"},
    )
    reject_response = client.post(
        "/change-requests/11/reject",
        headers={"X-Actor-Name": "local_admin"},
        json={"note": "no"},
    )

    assert create_response.status_code == 200
    assert create_response.json()["target_type"] == "tool_registry"
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"
    assert reject_response.status_code == 200
    assert reject_response.json()["status"] == "rejected"
    assert conn.commit_called == 3


def test_change_request_control_routes_apply_and_rollback():
    scenario = {
        "change_requests": {
            12: {
                "id": 12,
                "status": "approved",
                "target_type": "tool_registry",
                "target_key": "web_search",
                "source_workflow_proposal_id": 501,
            }
        }
    }
    client, conn = build_client(scenario)

    apply_response = client.post("/change-requests/12/apply", headers={"X-Actor-Name": "local_admin"})
    rollback_response = client.post("/change-requests/12/rollback", headers={"X-Actor-Name": "local_admin"})

    assert apply_response.status_code == 200
    assert apply_response.json()["status"] == "applied"
    assert rollback_response.status_code == 200
    assert rollback_response.json()["created"] is True
    assert rollback_response.json()["change_request"]["serialized"] is True
    assert conn.commit_called == 2


def test_change_request_control_routes_rollback_existing_and_conflict():
    existing_scenario = {
        "change_requests": {
            13: {"id": 13, "status": "applied", "target_type": "tool_registry", "target_key": "web_search"}
        },
        "existing_rollbacks": {
            13: {"id": 1301, "status": "pending", "target_type": "tool_registry", "target_key": "web_search"}
        },
    }
    client, _conn = build_client(existing_scenario)
    existing_response = client.post("/change-requests/13/rollback", headers={"X-Actor-Name": "local_admin"})

    conflict_scenario = {
        "change_requests": {
            14: {"id": 14, "status": "applied", "target_type": "tool_registry", "target_key": "web_search"}
        },
        "rollback_ready": False,
        "rollback_note": "no baseline",
    }
    conflict_client, _ = build_client(conflict_scenario)
    conflict_response = conflict_client.post("/change-requests/14/rollback", headers={"X-Actor-Name": "local_admin"})

    assert existing_response.status_code == 200
    assert existing_response.json()["created"] is False
    assert existing_response.json()["change_request"]["id"] == 1301
    assert conflict_response.status_code == 409


def test_change_request_control_routes_workflow_bridge_and_shadow_validate():
    scenario = {
        "workflow_proposals": {
            501: {"id": 501, "task_run_id": 77, "action_key": "model_route_patch"}
        }
    }
    client, conn = build_client(scenario)

    bridge_response = client.post(
        "/workflow-proposals/501/change-request-draft",
        headers={"X-Actor-Name": "local_admin"},
        json={"target_type": "model_route", "target_key": "planner", "proposed_payload": {"model_name": "gpt-5"}, "rationale": "upgrade"},
    )
    proposal_shadow_response = client.post(
        "/workflow-proposals/501/shadow-validate",
        headers={"X-Actor-Name": "local_admin"},
        json={"note": "check", "await_completion": False},
    )
    change_shadow_response = client.post(
        "/change-requests/21/shadow-validate",
        headers={"X-Actor-Name": "local_admin"},
        json={"note": "check", "await_completion": False},
    )

    assert bridge_response.status_code == 200
    assert bridge_response.json()["change_request"]["id"] == 202
    assert proposal_shadow_response.status_code == 200
    assert proposal_shadow_response.json()["shadow_task"]["id"] == 909
    assert change_shadow_response.status_code == 200
    assert change_shadow_response.json()["workflow_proposal"]["id"] == 501
    assert conn.commit_called == 3


def test_change_request_control_routes_permission_boundaries_are_stable():
    scenario = {
        "change_requests": {
            31: {"id": 31, "status": "pending", "target_type": "tool_registry", "target_key": "web_search"},
            32: {"id": 32, "status": "approved", "target_type": "tool_registry", "target_key": "web_search"},
            33: {"id": 33, "status": "applied", "target_type": "tool_registry", "target_key": "web_search"},
        },
        "workflow_proposals": {
            501: {"id": 501, "task_run_id": 77, "action_key": "model_route_patch"}
        },
    }
    client, _conn = build_client(scenario)

    create_response = client.post(
        "/change-requests",
        headers={"X-Actor-Name": "local_operator"},
        json={"target_type": "tool_registry", "target_key": "web_search", "proposed_payload": {"enabled": True}, "rationale": "open"},
    )
    approve_response = client.post(
        "/change-requests/31/approve",
        headers={"X-Actor-Name": "local_admin"},
        json={"note": "ok"},
    )
    apply_response = client.post("/change-requests/32/apply", headers={"X-Actor-Name": "local_admin"})
    rollback_response = client.post("/change-requests/33/rollback", headers={"X-Actor-Name": "local_operator"})
    bridge_response = client.post(
        "/workflow-proposals/501/change-request-draft",
        headers={"X-Actor-Name": "local_operator"},
        json={"target_type": "model_route", "target_key": "planner", "proposed_payload": {"model_name": "gpt-5"}, "rationale": "upgrade"},
    )
    shadow_response = client.post(
        "/workflow-proposals/501/shadow-validate",
        headers={"X-Actor-Name": "local_operator"},
        json={"note": "check", "await_completion": False},
    )

    assert create_response.status_code == 200
    assert approve_response.status_code == 200
    assert apply_response.status_code == 200
    assert rollback_response.status_code == 200
    assert bridge_response.status_code == 200
    assert shadow_response.status_code == 200
    assert scenario["permission_checks"] == [
        ("local_operator", "operate"),
        ("local_admin", "admin"),
        ("local_admin", "admin"),
        ("local_operator", "operate"),
        ("local_operator", "operate"),
        ("local_operator", "operate"),
    ]


def test_change_request_control_routes_admin_endpoints_reject_operator():
    scenario = {
        "change_requests": {
            41: {"id": 41, "status": "pending", "target_type": "tool_registry", "target_key": "web_search"},
            42: {"id": 42, "status": "approved", "target_type": "tool_registry", "target_key": "web_search"},
        }
    }
    client, _conn = build_client(
        scenario,
        require_actor_permission=lambda _cur, actor_name, permission: (
            (_ for _ in ()).throw(HTTPException(status_code=403, detail="forbidden"))
            if permission == "admin"
            else {"actor_name": actor_name or "local_operator", "role": "operator"}
        ),
    )

    approve_response = client.post(
        "/change-requests/41/approve",
        headers={"X-Actor-Name": "local_operator"},
        json={"note": "nope"},
    )
    apply_response = client.post("/change-requests/42/apply", headers={"X-Actor-Name": "local_operator"})

    assert approve_response.status_code == 403
    assert apply_response.status_code == 403
