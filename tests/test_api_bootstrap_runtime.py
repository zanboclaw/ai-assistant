from __future__ import annotations

import sys
from pathlib import Path

from fastapi import HTTPException

API_ROOT = Path(__file__).resolve().parents[1] / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from api_bootstrap_runtime import (
    enforce_change_gate_for_direct_update,
    fetch_planner_route,
    init_db_with_context,
    is_change_gate_enforced,
)


class FakeCursor:
    def __init__(self, *, fetchone_result=None):
        self.executed = []
        self.closed = False
        self.fetchone_result = fetchone_result

    def execute(self, sql, params=None):
        self.executed.append((" ".join(str(sql).split()), params))

    def fetchone(self):
        return self.fetchone_result

    def close(self):
        self.closed = True


class FakeConn:
    def __init__(self, cursor: FakeCursor):
        self.cursor_instance = cursor
        self.closed = False
        self.committed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


def test_fetch_planner_route_seeds_tables_then_queries():
    cursor = FakeCursor(fetchone_result={"route_name": "planner"})
    calls = []

    result = fetch_planner_route(
        cursor,
        seed_default_model_providers_fn=lambda cur: calls.append(("providers", cur)),
        seed_default_model_routes_fn=lambda cur: calls.append(("routes", cur)),
    )

    assert result == {"route_name": "planner"}
    assert calls == [("providers", cursor), ("routes", cursor)]
    assert "FROM model_routes" in cursor.executed[0][0]


def test_is_change_gate_enforced_and_guard_raise_expected_error():
    assert is_change_gate_enforced("model_route", default_enforced_change_target_types={"model_route"}) is True
    assert is_change_gate_enforced("risk_policy", default_enforced_change_target_types={"model_route"}) is False

    try:
        enforce_change_gate_for_direct_update(
            "model_route",
            is_change_gate_enforced_fn=lambda value: value == "model_route",
            http_exception_cls=HTTPException,
        )
    except HTTPException as exc:
        assert exc.status_code == 409
        assert "Direct update disabled" in exc.detail
    else:  # pragma: no cover
        raise AssertionError("expected HTTPException")


def test_init_db_with_context_runs_bootstrap_commit_and_logs():
    cursor = FakeCursor()
    conn = FakeConn(cursor)
    calls = []

    class FakeLogger:
        def info(self, message, actor_name):
            calls.append((message, actor_name))

    result = init_db_with_context(
        "local_admin",
        get_conn_fn=lambda: conn,
        require_actor_permission_fn=lambda cur, actor_name, permission: {
            "actor_name": actor_name,
            "permission": permission,
            "cur": cur,
        },
        ensure_runtime_core_tables_fn=lambda cur: calls.append(("runtime", cur)),
        seed_default_risk_policies_fn=lambda cur: calls.append(("risk", cur)),
        ensure_audit_logs_table_fn=lambda cur: calls.append(("audit", cur)),
        seed_default_access_actors_fn=lambda cur: calls.append(("actors", cur)),
        seed_default_access_quotas_fn=lambda cur: calls.append(("quotas", cur)),
        seed_default_tool_registry_fn=lambda cur: calls.append(("tools", cur)),
        seed_default_model_providers_fn=lambda cur: calls.append(("providers", cur)),
        seed_default_model_routes_fn=lambda cur: calls.append(("routes", cur)),
        ensure_change_requests_table_fn=lambda cur: calls.append(("change_requests", cur)),
        ensure_agent_tables_fn=lambda cur: calls.append(("agents", cur)),
        logger=FakeLogger(),
    )

    assert result == {"message": "database initialized"}
    assert conn.committed is True
    assert cursor.closed is True
    assert conn.closed is True
    assert calls[0] == ("runtime", cursor)
    assert calls[-1] == ("database initialized actor=%s", "local_admin")
