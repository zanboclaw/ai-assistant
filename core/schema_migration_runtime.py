from __future__ import annotations

RUNTIME_SCHEMA_FINALIZED_MIGRATION_ID = "0003_runtime_schema_finalize"


def is_schema_migration_applied(cur, migration_id: str) -> bool:
    cur.execute("SELECT to_regclass('public.schema_migrations') AS regclass;")
    row = cur.fetchone() or {}
    if not row.get("regclass"):
        return False
    cur.execute(
        "SELECT 1 FROM schema_migrations WHERE migration_id = %s LIMIT 1;",
        (migration_id,),
    )
    return cur.fetchone() is not None


def is_runtime_schema_finalized(cur) -> bool:
    return is_schema_migration_applied(cur, RUNTIME_SCHEMA_FINALIZED_MIGRATION_ID)
