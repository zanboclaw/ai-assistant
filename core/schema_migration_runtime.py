from __future__ import annotations

from core.runtime_schema_contracts import RUNTIME_SCHEMA_CONTRACT_MIGRATION_ID

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


def is_runtime_schema_contract_finalized(cur) -> bool:
    return is_schema_migration_applied(cur, RUNTIME_SCHEMA_CONTRACT_MIGRATION_ID)


def table_exists(cur, table_name: str) -> bool:
    cur.execute("SELECT to_regclass(%s) AS regclass;", (f"public.{table_name}",))
    row = cur.fetchone() or {}
    return bool(row.get("regclass"))


def table_has_columns(cur, table_name: str, required_columns: tuple[str, ...]) -> bool:
    if not table_exists(cur, table_name):
        return False
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = %s;
        """,
        (table_name,),
    )
    columns = {str(row.get("column_name") or "") for row in (cur.fetchall() or [])}
    return all(column_name in columns for column_name in required_columns)


def is_schema_contract_ready(
    cur,
    *,
    migration_id: str,
    table_name: str,
    required_columns: tuple[str, ...],
) -> bool:
    if is_schema_migration_applied(cur, migration_id):
        return True
    return table_has_columns(cur, table_name, required_columns)
