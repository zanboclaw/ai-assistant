import sys
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1] / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from schema_runtime import ApiSchemaRuntime


class ContractReadyCursor:
    def __init__(self):
        self.executed = []
        self._last_query = ""

    def execute(self, query, params=None):
        self._last_query = " ".join(str(query).split())
        self.executed.append((self._last_query, params))

    def fetchone(self):
        if "SELECT to_regclass('public.schema_migrations')" in self._last_query:
            return {"regclass": "schema_migrations"}
        if "SELECT 1 FROM schema_migrations" in self._last_query:
            return {"migration_id": "0012_runtime_schema_contract_finalize"}
        return None


class MissingSchemaCursor(ContractReadyCursor):
    def fetchone(self):
        if "SELECT to_regclass('public.schema_migrations')" in self._last_query:
            return {"regclass": None}
        return None


def test_ensure_runtime_core_tables_only_validates_contracts():
    runtime = ApiSchemaRuntime(get_conn=lambda: None)
    runtime._runtime_core_schema_bootstrap_active = True
    cur = ContractReadyCursor()

    runtime.ensure_runtime_core_tables(cur)

    sql = "\n".join(query for query, _params in cur.executed)
    assert "CREATE TABLE" not in sql
    assert "ALTER TABLE" not in sql


def test_ensure_change_requests_table_raises_when_contract_missing():
    runtime = ApiSchemaRuntime(get_conn=lambda: None)
    cur = MissingSchemaCursor()

    try:
        runtime.ensure_change_requests_table(cur)
    except RuntimeError as exc:
        assert "run_migrations.py" in str(exc)
        assert "change_requests" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected runtime schema contract check to fail")
