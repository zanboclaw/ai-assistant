from core.long_term_memory import (
    LONG_TERM_MEMORY_SCHEMA_MIGRATION_ID,
    assert_long_term_memory_schema_ready,
    is_long_term_memory_schema_ready,
)


class FakeCursor:
    def __init__(self, *, fetchone_results=None, fetchall_results=None):
        self.fetchone_results = list(fetchone_results or [])
        self.fetchall_results = list(fetchall_results or [])
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((" ".join(str(sql).split()), params))

    def fetchone(self):
        if self.fetchone_results:
            return self.fetchone_results.pop(0)
        return None

    def fetchall(self):
        if self.fetchall_results:
            return self.fetchall_results.pop(0)
        return []


def test_is_long_term_memory_schema_ready_when_finalize_migration_applied():
    cur = FakeCursor(
        fetchone_results=[
            {"regclass": "schema_migrations"},
            {"migration_id": LONG_TERM_MEMORY_SCHEMA_MIGRATION_ID},
        ]
    )

    assert is_long_term_memory_schema_ready(cur) is True


def test_is_long_term_memory_schema_ready_falls_back_to_column_probe():
    cur = FakeCursor(
        fetchone_results=[
            {"regclass": "schema_migrations"},
            None,
            {"regclass": "long_term_memories"},
        ],
        fetchall_results=[
            [
                {"column_name": "memory_key"},
                {"column_name": "memory_kind"},
                {"column_name": "source_session_id"},
                {"column_name": "source_task_id"},
                {"column_name": "actor_name"},
                {"column_name": "title"},
                {"column_name": "content"},
                {"column_name": "keywords_json"},
                {"column_name": "metadata_json"},
                {"column_name": "hit_count"},
                {"column_name": "created_at"},
                {"column_name": "updated_at"},
            ]
        ],
    )

    assert is_long_term_memory_schema_ready(cur) is True


def test_assert_long_term_memory_schema_ready_raises_when_schema_missing():
    cur = FakeCursor(
        fetchone_results=[
            {"regclass": None},
            {"regclass": None},
        ]
    )

    try:
        assert_long_term_memory_schema_ready(cur)
    except RuntimeError as exc:
        assert "run_migrations.py" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected schema assertion to fail")
