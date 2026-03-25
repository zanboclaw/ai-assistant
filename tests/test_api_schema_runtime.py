import sys
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1] / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from schema_runtime import ApiSchemaRuntime


class FakeCursor:
    def __init__(self, fetchone_results=None):
        self.fetchone_results = list(fetchone_results or [])
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((" ".join(str(query).split()), params))

    def fetchone(self):
        if self.fetchone_results:
            return self.fetchone_results.pop(0)
        return None


def test_ensure_runtime_core_tables_skips_column_backfill_when_migration_finalized():
    runtime = ApiSchemaRuntime(get_conn=lambda: None)
    runtime._runtime_core_schema_bootstrap_active = True
    cur = FakeCursor(
        fetchone_results=[
            {"regclass": "schema_migrations"},
            {"migration_id": "0003_runtime_schema_finalize"},
            {"regclass": "schema_migrations"},
            {"migration_id": "0003_runtime_schema_finalize"},
        ]
    )

    runtime.ensure_runtime_core_tables(cur)

    sql = "\n".join(query for query, _params in cur.executed)
    assert "ALTER TABLE task_runs" not in sql
    assert "ALTER TABLE task_steps" not in sql


def test_ensure_change_requests_table_skips_column_backfill_when_migration_finalized():
    runtime = ApiSchemaRuntime(get_conn=lambda: None)
    cur = FakeCursor(
        fetchone_results=[
            {"regclass": None},
            {"regclass": None},
            {"regclass": "schema_migrations"},
            {"migration_id": "0003_runtime_schema_finalize"},
        ]
    )

    runtime.ensure_change_requests_table(cur)

    sql = "\n".join(query for query, _params in cur.executed)
    assert "CREATE TABLE IF NOT EXISTS change_requests" in sql
    assert "ALTER TABLE change_requests" not in sql
