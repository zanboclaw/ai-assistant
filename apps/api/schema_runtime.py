from __future__ import annotations

import threading

from core.runtime_schema_contracts import (
    AGENT_TABLE_CONTRACTS,
    AUDIT_LOGS_REQUIRED_COLUMNS,
    CHANGE_REQUESTS_REQUIRED_COLUMNS,
    EVALUATOR_RUNS_REQUIRED_COLUMNS,
    RUNTIME_CORE_TABLE_CONTRACTS,
    RUNTIME_SCHEMA_CONTRACT_MIGRATION_ID,
    SESSION_TABLE_CONTRACTS,
    SKILL_TABLE_CONTRACTS,
    TRACE_TABLE_CONTRACTS,
)
from core.schema_migration_runtime import is_schema_contract_ready


class ApiSchemaRuntime:
    def __init__(self, *, get_conn):
        self._get_conn = get_conn
        self._stage56_schema_bootstrap_lock = threading.Lock()
        self._stage56_schema_bootstrap_active = False
        self._stage56_schema_bootstrapped = False
        self._runtime_core_schema_bootstrap_lock = threading.Lock()
        self._runtime_core_schema_bootstrap_active = False
        self._runtime_core_schema_bootstrapped = False
        self._change_requests_schema_bootstrap_lock = threading.Lock()
        self._change_requests_schema_bootstrapped = False
        self._schema_ready_flags: dict[str, bool] = {}

    def _table_exists(self, cur, table_name: str) -> bool:
        cur.execute("SELECT to_regclass(%s) AS regclass;", (f"public.{table_name}",))
        row = cur.fetchone() or {}
        return bool(row.get("regclass"))

    def _column_exists(self, cur, table_name: str, column_name: str) -> bool:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
              AND column_name = %s
            LIMIT 1;
            """,
            (table_name, column_name),
        )
        return cur.fetchone() is not None

    def _schema_contract_ready(self, cur, *, table_name: str, required_columns: tuple[str, ...]) -> bool:
        return is_schema_contract_ready(
            cur,
            migration_id=RUNTIME_SCHEMA_CONTRACT_MIGRATION_ID,
            table_name=table_name,
            required_columns=required_columns,
        )

    def _ensure_contract(self, cur, *, table_name: str, required_columns: tuple[str, ...]) -> None:
        if self._schema_ready_flags.get(table_name):
            return
        if self._schema_contract_ready(cur, table_name=table_name, required_columns=required_columns):
            self._schema_ready_flags[table_name] = True
            return
        raise RuntimeError(
            f"{table_name} schema is not ready. Please run `python3 scripts/run_migrations.py` before starting API."
        )

    def _change_requests_schema_ready(self, cur) -> bool:
        return self._schema_contract_ready(
            cur,
            table_name="change_requests",
            required_columns=CHANGE_REQUESTS_REQUIRED_COLUMNS,
        )

    def _stage56_schema_ready(self, cur) -> bool:
        table_contracts = dict(AGENT_TABLE_CONTRACTS)
        table_contracts["evaluator_runs"] = EVALUATOR_RUNS_REQUIRED_COLUMNS
        return all(
            self._schema_contract_ready(cur, table_name=table_name, required_columns=required_columns)
            for table_name, required_columns in table_contracts.items()
        )

    def ensure_change_requests_table(self, cur):
        if self._change_requests_schema_bootstrapped:
            return

        with self._change_requests_schema_bootstrap_lock:
            if self._change_requests_schema_bootstrapped:
                return
            self._ensure_contract(
                cur,
                table_name="change_requests",
                required_columns=CHANGE_REQUESTS_REQUIRED_COLUMNS,
            )
            self._change_requests_schema_bootstrapped = True

    def ensure_stage56_schema_bootstrapped(self):
        if self._stage56_schema_bootstrapped:
            return

        with self._stage56_schema_bootstrap_lock:
            if self._stage56_schema_bootstrapped:
                return

            conn = self._get_conn()
            cur = conn.cursor()
            self._stage56_schema_bootstrap_active = True
            try:
                self.ensure_audit_logs_table(cur)
                self.ensure_agent_tables(cur)
                self.ensure_evaluator_tables(cur)
                conn.commit()
                self._stage56_schema_bootstrapped = True
            finally:
                self._stage56_schema_bootstrap_active = False
                cur.close()
                conn.close()

    def ensure_runtime_core_schema_bootstrapped(self):
        if self._runtime_core_schema_bootstrapped:
            return

        with self._runtime_core_schema_bootstrap_lock:
            if self._runtime_core_schema_bootstrapped:
                return

            conn = self._get_conn()
            cur = conn.cursor()
            self._runtime_core_schema_bootstrap_active = True
            try:
                self.ensure_runtime_core_tables(cur)
                conn.commit()
                self._runtime_core_schema_bootstrapped = True
            finally:
                self._runtime_core_schema_bootstrap_active = False
                cur.close()
                conn.close()

    def ensure_runtime_core_tables(self, cur):
        if not self._runtime_core_schema_bootstrap_active:
            self.ensure_runtime_core_schema_bootstrapped()
            return

        self.ensure_sessions_tables(cur)
        self.ensure_trace_tables(cur)
        for table_name, required_columns in RUNTIME_CORE_TABLE_CONTRACTS.items():
            self._ensure_contract(cur, table_name=table_name, required_columns=required_columns)

    def ensure_audit_logs_table(self, cur):
        if not self._stage56_schema_bootstrap_active:
            self.ensure_stage56_schema_bootstrapped()
            return
        self._ensure_contract(cur, table_name="audit_logs", required_columns=AUDIT_LOGS_REQUIRED_COLUMNS)

    def ensure_trace_tables(self, cur):
        for table_name, required_columns in TRACE_TABLE_CONTRACTS.items():
            self._ensure_contract(cur, table_name=table_name, required_columns=required_columns)

    def ensure_skill_registry_tables(self, cur):
        for table_name, required_columns in SKILL_TABLE_CONTRACTS.items():
            self._ensure_contract(cur, table_name=table_name, required_columns=required_columns)

    def ensure_agent_tables(self, cur):
        if self._stage56_schema_bootstrapped:
            return
        if self._stage56_schema_ready(cur):
            self._stage56_schema_bootstrapped = True
            return
        if not self._stage56_schema_bootstrap_active:
            self.ensure_stage56_schema_bootstrapped()
            return
        for table_name, required_columns in AGENT_TABLE_CONTRACTS.items():
            self._ensure_contract(cur, table_name=table_name, required_columns=required_columns)
        self._stage56_schema_bootstrapped = self._stage56_schema_ready(cur)

    def ensure_evaluator_tables(self, cur):
        if self._stage56_schema_bootstrapped:
            return
        if self._stage56_schema_ready(cur):
            self._stage56_schema_bootstrapped = True
            return
        if not self._stage56_schema_bootstrap_active:
            self.ensure_stage56_schema_bootstrapped()
            return
        self.ensure_agent_tables(cur)
        self._ensure_contract(
            cur,
            table_name="evaluator_runs",
            required_columns=EVALUATOR_RUNS_REQUIRED_COLUMNS,
        )
        self._stage56_schema_bootstrapped = self._stage56_schema_ready(cur)

    def ensure_sessions_base_table(self, cur):
        self._ensure_contract(cur, table_name="sessions", required_columns=SESSION_TABLE_CONTRACTS["sessions"])

    def ensure_sessions_tables(self, cur):
        for table_name, required_columns in SESSION_TABLE_CONTRACTS.items():
            self._ensure_contract(cur, table_name=table_name, required_columns=required_columns)
