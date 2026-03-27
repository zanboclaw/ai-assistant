#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "apps" / "api"
for path in (ROOT, API_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


DB_CONFIG = {
    "host": os.environ.get("POSTGRES_HOST", "postgres"),
    "dbname": os.environ.get("POSTGRES_DB", "assistant"),
    "user": os.environ.get("POSTGRES_USER", "assistant"),
    "password": os.environ.get("POSTGRES_PASSWORD", "change_me_for_local_dev"),
}

LEGACY_MIGRATIONS_DIR = ROOT / "migrations"
SQL_MIGRATIONS_DIR = ROOT / "db" / "migrations"


def get_conn():
    last_error: Exception | None = None
    for _ in range(20):
        try:
            return psycopg2.connect(cursor_factory=RealDictCursor, **DB_CONFIG)
        except psycopg2.OperationalError as exc:
            last_error = exc
            time.sleep(1)
    if last_error is not None:
        raise last_error
    raise RuntimeError("unable to connect to postgres")


def ensure_schema_migrations_table(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            migration_id TEXT PRIMARY KEY,
            description TEXT NOT NULL DEFAULT '',
            applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def load_migration_module(path: Path):
    spec = importlib.util.spec_from_file_location(f"migration_{path.stem}", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load migration module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def iter_migration_paths() -> list[Path]:
    paths: list[Path] = []
    if SQL_MIGRATIONS_DIR.exists():
        paths.extend(sorted(path for path in SQL_MIGRATIONS_DIR.glob("*.sql")))
    if LEGACY_MIGRATIONS_DIR.exists():
        paths.extend(sorted(path for path in LEGACY_MIGRATIONS_DIR.glob("*.py") if path.name != "__init__.py"))
    return paths


def load_sql_migration(path: Path):
    sql = path.read_text(encoding="utf-8")

    class SqlMigration:
        MIGRATION_ID = path.stem
        DESCRIPTION = sql.splitlines()[0][:120] if sql.splitlines() else ""

        @staticmethod
        def apply(cur):
            cur.execute(sql)

    return SqlMigration


def migration_applied(cur, migration_id: str) -> bool:
    cur.execute("SELECT 1 FROM schema_migrations WHERE migration_id = %s;", (migration_id,))
    return bool(cur.fetchone())


def mark_migration_applied(cur, migration_id: str, description: str) -> None:
    cur.execute(
        """
        INSERT INTO schema_migrations (migration_id, description)
        VALUES (%s, %s)
        ON CONFLICT (migration_id) DO NOTHING;
        """,
        (migration_id, description),
    )


def run() -> None:
    conn = get_conn()
    cur = conn.cursor()
    try:
        ensure_schema_migrations_table(cur)
        conn.commit()
        for migration_path in iter_migration_paths():
            if migration_path.suffix == ".sql":
                module = load_sql_migration(migration_path)
            else:
                module = load_migration_module(migration_path)
            migration_id = str(getattr(module, "MIGRATION_ID", migration_path.stem))
            description = str(getattr(module, "DESCRIPTION", "")).strip()
            apply_fn = getattr(module, "apply", None)
            if not callable(apply_fn):
                raise RuntimeError(f"Migration {migration_path} missing callable apply(cur)")
            if migration_applied(cur, migration_id):
                continue
            apply_fn(cur)
            mark_migration_applied(cur, migration_id, description)
            conn.commit()
            print(f"applied migration {migration_id}")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    run()
