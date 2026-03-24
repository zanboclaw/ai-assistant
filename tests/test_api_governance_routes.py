from __future__ import annotations

from copy import deepcopy

from fastapi import FastAPI
from fastapi.testclient import TestClient

import governance_routes


class GovernanceCursor:
    def __init__(self, scenario: dict):
        self.scenario = scenario
        self._fetchone = None
        self._fetchall = []

    def execute(self, sql, params=None):
        normalized = " ".join(str(sql).split())

        if "FROM risk_policies" in normalized:
            self._fetchall = deepcopy(self.scenario.get("risk_rows", []))
            return

        if "FROM tool_registry_entries" in normalized:
            self._fetchall = deepcopy(self.scenario.get("tool_rows", []))
            return

        if "FROM model_routes" in normalized:
            self._fetchall = deepcopy(self.scenario.get("model_route_rows", []))
            return

        if "FROM model_providers" in normalized:
            self._fetchall = deepcopy(self.scenario.get("model_provider_rows", []))
            return

        if "FROM access_actors" in normalized and "permission_overrides" in normalized:
            self._fetchall = deepcopy(self.scenario.get("access_actor_rows", []))
            return

        if "FROM access_quotas" in normalized and "created_at" in normalized and "JOIN access_quotas" not in normalized:
            self._fetchall = deepcopy(self.scenario.get("access_quota_rows", []))
            return

        if "JOIN access_quotas q ON q.actor_name = a.actor_name" in normalized:
            self._fetchall = deepcopy(self.scenario.get("quota_usage_rows", []))
            return

        if "FROM audit_logs" in normalized:
            self._fetchall = deepcopy(self.scenario.get("audit_rows", []))
            return

        self._fetchone = None
        self._fetchall = []

    def fetchone(self):
        return deepcopy(self._fetchone)

    def fetchall(self):
        return deepcopy(self._fetchall)

    def close(self):
        return None


class GovernanceConn:
    def __init__(self, cursor: GovernanceCursor):
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
    cursor = GovernanceCursor(scenario)
    conn = GovernanceConn(cursor)
    logger = FakeLogger()
    scenario["audit_logs"] = []
    scenario["gate_targets"] = []

    app = FastAPI()
    app.include_router(
        governance_routes.register_governance_routes(
            get_conn=lambda: conn,
            require_actor_permission=lambda _cur, actor_name, permission: {
                "actor_name": actor_name or "local_admin",
                "role": "admin",
                "permission": permission,
            },
            seed_default_risk_policies=lambda _cur: None,
            deserialize_policy_row=lambda row: {"policy_key": row["policy_key"], "policy_value": row["policy_value"]},
            seed_default_tool_registry=lambda _cur: None,
            serialize_tool_registry_row=lambda row: dict(row),
            seed_default_model_providers=lambda _cur: None,
            seed_default_model_routes=lambda _cur: None,
            serialize_model_route_row=lambda row: dict(row),
            serialize_model_provider_row=lambda row: dict(row),
            seed_default_access_actors=lambda _cur: None,
            seed_default_access_quotas=lambda _cur: None,
            serialize_access_actor_row=lambda row: {
                "actor_name": row["actor_name"],
                "role": row["role"],
                "permissions": sorted(row["permissions"]),
            },
            serialize_access_quota_row=lambda row: dict(row),
            parse_maybe_json=lambda value: value if not isinstance(value, str) else [],
            validate_policy_value=lambda policy_key, policy_value: ("json", {"policy_key": policy_key, "value": policy_value}),
            update_risk_policy_entry=lambda _cur, **kwargs: {"policy_key": kwargs["policy_key"], "value": kwargs["policy_value"]},
            update_tool_registry_entry=lambda _cur, **kwargs: {"tool_name": kwargs["tool_name"], "risk_level": kwargs["risk_level"]},
            update_model_route_entry=lambda _cur, **kwargs: {"route_name": kwargs["route_name"], "model_name": kwargs["model_name"]},
            upsert_model_provider_entry=lambda _cur, **kwargs: {"provider_name": kwargs["provider_name"], "driver": kwargs["driver"]},
            upsert_access_actor=lambda _cur, **kwargs: {"actor_name": kwargs["actor_name"], "role": kwargs["role"]},
            upsert_access_quota=lambda _cur, **kwargs: {"actor_name": kwargs["actor_name"], "daily_task_limit": kwargs["daily_task_limit"]},
            upsert_default_access_quota=lambda _cur, _actor_name: None,
            insert_audit_log=lambda _cur, event_type, actor, task_id, details: scenario["audit_logs"].append(
                (event_type, actor, task_id, details)
            ),
            enforce_change_gate_for_direct_update=lambda target: scenario["gate_targets"].append(target),
            ensure_audit_logs_table=lambda _cur: None,
            access_role_permissions={"admin": {"read", "operate", "admin"}, "operator": {"read", "operate"}},
            step_request_protocol_version="stage2-v1",
            step_execution_request_fields=["step_order", "tool_name"],
            enriched_step_execution_request_extra_fields=["resolved_input", "should_run"],
            multi_agent_protocol_version="multi-agent-v1",
            auto_stage5_postrun_enabled=True,
            logger=logger,
        )
    )
    return TestClient(app), conn, logger


def test_governance_routes_list_risk_policies():
    scenario = {"risk_rows": [{"policy_key": "web_search", "policy_value": {"max_results": 5}}]}
    client, conn, _logger = build_client(scenario)

    response = client.get("/risk-policies", headers={"X-Actor-Name": "local_admin"})

    assert response.status_code == 200
    assert response.json()[0]["policy_key"] == "web_search"
    assert conn.commit_called == 1


def test_governance_routes_update_tool_registry_enforces_validation_and_gate():
    scenario = {}
    client, conn, logger = build_client(scenario)

    bad_response = client.put(
        "/tools/web_search",
        headers={"X-Actor-Name": "local_admin"},
        json={"enabled": True, "risk_level": "critical", "provider_type": "builtin", "transport": "local"},
    )
    ok_response = client.put(
        "/tools/web_search",
        headers={"X-Actor-Name": "local_admin"},
        json={
            "enabled": True,
            "risk_level": "high",
            "provider_type": "builtin",
            "transport": "local",
            "server_name": "",
            "provider_config": {},
            "approval_required": True,
            "description": "search",
        },
    )

    assert bad_response.status_code == 400
    assert ok_response.status_code == 200
    assert ok_response.json()["tool_name"] == "web_search"
    assert conn.commit_called == 1
    assert scenario["gate_targets"] == ["tool_registry"]
    assert "tool registry updated" in logger.messages[0]


def test_governance_routes_list_access_quota_usage():
    scenario = {
        "quota_usage_rows": [
            {
                "actor_name": "local_admin",
                "role": "admin",
                "daily_task_limit": 10,
                "active_task_limit": 3,
                "daily_token_limit": 1000,
                "max_parallel_agents": 2,
                "daily_task_count": 4,
                "active_task_count": 1,
                "daily_token_count": 200,
            }
        ]
    }
    client, _conn, _logger = build_client(scenario)

    response = client.get("/access/quota-usage", headers={"X-Actor-Name": "local_admin"})

    assert response.status_code == 200
    payload = response.json()[0]
    assert payload["daily_remaining"] == 6
    assert payload["daily_token_remaining"] == 800


def test_governance_routes_list_audit_logs_parses_details():
    scenario = {
        "audit_rows": [
            {"id": 1, "task_id": 8, "event_type": "task.resume", "actor": "local_admin", "details": {"from_step": 2}, "created_at": "now"}
        ]
    }
    client, _conn, _logger = build_client(scenario)

    response = client.get("/audit-logs?task_id=8", headers={"X-Actor-Name": "local_admin"})

    assert response.status_code == 200
    assert response.json()[0]["details"]["from_step"] == 2


def test_governance_routes_runtime_metadata_reflects_protocol_versions():
    scenario = {}
    client, _conn, _logger = build_client(scenario)

    response = client.get("/runtime-metadata", headers={"X-Actor-Name": "local_admin"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["step_request_protocol"]["version"] == "stage2-v1"
    assert payload["multi_agent_protocol"]["version"] == "multi-agent-v1"
    assert payload["evaluator_protocol"]["source"] == "task_runtime_postrun_v1"
