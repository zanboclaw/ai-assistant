import pytest
from fastapi import HTTPException

from access_control import enforce_task_quota, ensure_access_actors_table, ensure_access_quotas_table, require_actor_permission


class DummyCursor:
    def __init__(self, fetchone_values=None):
        self.fetchone_values = list(fetchone_values or [])
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        if not self.fetchone_values:
            return {}
        return self.fetchone_values.pop(0)


def test_require_actor_permission_allows_operator_read(monkeypatch):
    monkeypatch.setattr(
        "access_control.resolve_actor_context",
        lambda cur, actor_name: {"actor_name": actor_name or "local_operator", "role": "operator"},
    )

    actor = require_actor_permission(DummyCursor(), "local_operator", "read")
    assert actor["role"] == "operator"


def test_require_actor_permission_blocks_viewer_operate(monkeypatch):
    monkeypatch.setattr(
        "access_control.resolve_actor_context",
        lambda cur, actor_name: {"actor_name": actor_name or "local_viewer", "role": "viewer"},
    )

    with pytest.raises(HTTPException) as exc:
        require_actor_permission(DummyCursor(), "local_viewer", "operate")

    assert exc.value.status_code == 403
    assert "lacks permission" in exc.value.detail


def test_require_actor_permission_allows_permission_override(monkeypatch):
    monkeypatch.setattr(
        "access_control.resolve_actor_context",
        lambda cur, actor_name: {
            "actor_name": actor_name or "custom_actor",
            "role": "viewer",
            "permissions": ["read", "memory_admin"],
        },
    )

    actor = require_actor_permission(DummyCursor(), "custom_actor", "memory_admin")
    assert actor["actor_name"] == "custom_actor"


def test_enforce_task_quota_blocks_when_parallel_budget_reached(monkeypatch):
    monkeypatch.setattr(
        "access_control.get_actor_quota_or_404",
        lambda cur, actor_name: {
            "daily_task_limit": 10,
            "active_task_limit": 10,
            "daily_token_limit": 0,
            "max_parallel_agents": 2,
        },
    )
    cur = DummyCursor(
        fetchone_values=[
            {"count": 1},
            {"count": 2},
        ]
    )

    with pytest.raises(HTTPException) as exc:
        enforce_task_quota(cur, "local_operator")

    assert exc.value.status_code == 429
    assert "max parallel task budget" in exc.value.detail


def test_enforce_task_quota_blocks_when_daily_token_limit_reached(monkeypatch):
    monkeypatch.setattr(
        "access_control.get_actor_quota_or_404",
        lambda cur, actor_name: {
            "daily_task_limit": 10,
            "active_task_limit": 10,
            "daily_token_limit": 100,
            "max_parallel_agents": 10,
        },
    )
    cur = DummyCursor(
        fetchone_values=[
            {"count": 1},
            {"count": 1},
            {"regclass": "agent_runs"},
            {"count": 120},
        ]
    )

    with pytest.raises(HTTPException) as exc:
        enforce_task_quota(cur, "local_operator")

    assert exc.value.status_code == 429
    assert "daily token limit" in exc.value.detail


def test_ensure_access_tables_accept_migration_managed_schema():
    cur = DummyCursor(
        fetchone_values=[
            {"regclass": "schema_migrations"},
            {"migration_id": "0011_api_governance_schema_finalize"},
            {"regclass": "schema_migrations"},
            {"migration_id": "0011_api_governance_schema_finalize"},
        ]
    )

    ensure_access_actors_table(cur)
    ensure_access_quotas_table(cur)

    sql = "\n".join(str(query) for query, _params in cur.executed)
    assert "CREATE TABLE" not in sql
    assert "ALTER TABLE" not in sql
