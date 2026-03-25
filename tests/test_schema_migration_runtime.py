from core.schema_migration_runtime import is_runtime_schema_finalized


class FakeCursor:
    def __init__(self, fetchone_results=None):
        self.fetchone_results = list(fetchone_results or [])
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        if self.fetchone_results:
            return self.fetchone_results.pop(0)
        return None


def test_is_runtime_schema_finalized_requires_schema_migrations_marker():
    cur = FakeCursor(fetchone_results=[{"regclass": None}])
    assert is_runtime_schema_finalized(cur) is False


def test_is_runtime_schema_finalized_returns_true_when_migration_row_exists():
    cur = FakeCursor(fetchone_results=[{"regclass": "schema_migrations"}, {"migration_id": "0003_runtime_schema_finalize"}])
    assert is_runtime_schema_finalized(cur) is True
