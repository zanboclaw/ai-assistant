import governance_helpers
from governance_helpers import (
    ensure_model_providers_table,
    ensure_model_routes_table,
    ensure_tool_registry_table,
)
from risk_policy_helpers import ensure_risk_policies_table


class FakeCursor:
    def __init__(self, *, fetchone_results=None, fetchall_results=None):
        self.fetchone_results = list(fetchone_results or [])
        self.fetchall_results = list(fetchall_results or [])
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((" ".join(str(query).split()), params))

    def fetchone(self):
        if self.fetchone_results:
            return self.fetchone_results.pop(0)
        return None

    def fetchall(self):
        if self.fetchall_results:
            return self.fetchall_results.pop(0)
        return []


def test_governance_schema_helpers_accept_migration_managed_tables():
    cur = FakeCursor(
        fetchone_results=[
            {"regclass": "schema_migrations"},
            {"migration_id": "0011_api_governance_schema_finalize"},
            {"regclass": "schema_migrations"},
            {"migration_id": "0011_api_governance_schema_finalize"},
            {"regclass": "schema_migrations"},
            {"migration_id": "0011_api_governance_schema_finalize"},
            {"regclass": "schema_migrations"},
            {"migration_id": "0011_api_governance_schema_finalize"},
        ]
    )

    ensure_tool_registry_table(cur)
    ensure_model_routes_table(cur)
    ensure_model_providers_table(cur)
    ensure_risk_policies_table(cur)

    sql = "\n".join(str(query) for query, _params in cur.executed)
    assert "CREATE TABLE" not in sql
    assert "ALTER TABLE" not in sql


def test_governance_schema_helpers_raise_when_schema_missing():
    governance_helpers._SCHEMA_FLAGS["tool_registry_entries"] = False
    governance_helpers._SCHEMA_FLAGS["model_routes"] = False
    governance_helpers._SCHEMA_FLAGS["model_providers"] = False
    cur = FakeCursor(
        fetchone_results=[
            {"regclass": None},
            {"regclass": None},
            {"regclass": None},
            {"regclass": None},
        ]
    )

    try:
        ensure_tool_registry_table(cur)
    except RuntimeError as exc:
        assert "run_migrations.py" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected schema assertion to fail")
