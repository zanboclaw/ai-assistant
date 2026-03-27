from apps.worker.infrastructure.db.runtime_schema import WorkerSchemaRuntime


class FakeCursor:
    def __init__(self):
        self.executed = []
        self._last_query = ""

    def execute(self, sql, params=None):
        self._last_query = " ".join(str(sql).split())
        self.executed.append((self._last_query, params))

    def fetchone(self):
        if "SELECT to_regclass('public.schema_migrations')" in self._last_query:
            return {"regclass": "schema_migrations"}
        if "SELECT 1 FROM schema_migrations" in self._last_query:
            return {"migration_id": "0012_runtime_schema_contract_finalize"}
        return None

    def close(self):
        pass


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def close(self):
        pass


def test_worker_schema_runtime_bootstrap_validates_contracts_and_seeds_defaults():
    cursor = FakeCursor()
    conn = FakeConn(cursor)
    calls = []
    runtime = WorkerSchemaRuntime(
        get_conn=lambda: conn,
        is_runtime_schema_finalized=lambda cur: False,
        seed_default_tool_registry=lambda cur: calls.append("tools"),
        seed_default_model_providers=lambda cur: calls.append("providers"),
        seed_default_model_routes=lambda cur: calls.append("routes"),
    )

    runtime.ensure_runtime_schema_bootstrapped()

    assert conn.committed is True
    assert calls == ["tools", "providers", "routes"]
    sql = "\n".join(statement for statement, _ in cursor.executed)
    assert "CREATE TABLE" not in sql
    assert "ALTER TABLE" not in sql
