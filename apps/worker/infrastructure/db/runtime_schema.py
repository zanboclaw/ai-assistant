from __future__ import annotations

import threading

from core.runtime_schema_contracts import (
    AGENT_TABLE_CONTRACTS,
    AUDIT_LOGS_REQUIRED_COLUMNS,
    EVALUATOR_RUNS_REQUIRED_COLUMNS,
    RUNTIME_CORE_TABLE_CONTRACTS,
    RUNTIME_SCHEMA_CONTRACT_MIGRATION_ID,
    SESSION_TABLE_CONTRACTS,
    SKILL_TABLE_CONTRACTS,
    TRACE_TABLE_CONTRACTS,
)
from core.schema_migration_runtime import is_schema_contract_ready


class WorkerSchemaRuntime:
    def __init__(
        self,
        *,
        get_conn,
        is_runtime_schema_finalized,
        seed_default_tool_registry,
        seed_default_model_providers,
        seed_default_model_routes,
    ) -> None:
        self._get_conn = get_conn
        self._is_runtime_schema_finalized = is_runtime_schema_finalized
        self._seed_default_tool_registry = seed_default_tool_registry
        self._seed_default_model_providers = seed_default_model_providers
        self._seed_default_model_routes = seed_default_model_routes
        self._runtime_schema_bootstrap_lock = threading.Lock()
        self._runtime_schema_bootstrap_active = False
        self._runtime_schema_bootstrapped = False
        self._schema_ready_flags: dict[str, bool] = {}

    @property
    def runtime_schema_bootstrap_active(self) -> bool:
        return self._runtime_schema_bootstrap_active

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
            f"{table_name} schema is not ready. Please run `python3 scripts/run_migrations.py` before starting Worker."
        )

    def ensure_runtime_schema_bootstrapped(self) -> None:
        if self._runtime_schema_bootstrapped:
            return

        with self._runtime_schema_bootstrap_lock:
            if self._runtime_schema_bootstrapped:
                return

            conn = self._get_conn()
            cur = conn.cursor()
            self._runtime_schema_bootstrap_active = True
            try:
                self.ensure_task_steps_columns(cur)
                self.ensure_approvals_table(cur)
                self.ensure_audit_logs_table(cur)
                self.ensure_trace_tables(cur)
                self.ensure_skill_registry_tables(cur)
                self._seed_default_tool_registry(cur)
                self._seed_default_model_providers(cur)
                self._seed_default_model_routes(cur)
                self.ensure_agent_tables(cur)
                self.ensure_evaluator_tables(cur)
                conn.commit()
                self._runtime_schema_bootstrapped = True
            finally:
                self._runtime_schema_bootstrap_active = False
                cur.close()
                conn.close()

    def ensure_task_steps_columns(self, cur) -> None:
        if not self._runtime_schema_bootstrap_active:
            self.ensure_runtime_schema_bootstrapped()
            return
        self._ensure_contract(cur, table_name="task_runs", required_columns=RUNTIME_CORE_TABLE_CONTRACTS["task_runs"])
        self._ensure_contract(cur, table_name="task_steps", required_columns=RUNTIME_CORE_TABLE_CONTRACTS["task_steps"])

    def ensure_approvals_table(self, cur) -> None:
        if not self._runtime_schema_bootstrap_active:
            self.ensure_runtime_schema_bootstrapped()
            return
        self._ensure_contract(cur, table_name="approvals", required_columns=RUNTIME_CORE_TABLE_CONTRACTS["approvals"])

    def ensure_audit_logs_table(self, cur) -> None:
        if not self._runtime_schema_bootstrap_active:
            self.ensure_runtime_schema_bootstrapped()
            return
        self._ensure_contract(cur, table_name="audit_logs", required_columns=AUDIT_LOGS_REQUIRED_COLUMNS)

    def ensure_trace_tables(self, cur) -> None:
        if not self._runtime_schema_bootstrap_active:
            self.ensure_runtime_schema_bootstrapped()
            return
        for table_name, required_columns in TRACE_TABLE_CONTRACTS.items():
            self._ensure_contract(cur, table_name=table_name, required_columns=required_columns)

    def ensure_skill_registry_tables(self, cur) -> None:
        if not self._runtime_schema_bootstrap_active:
            self.ensure_runtime_schema_bootstrapped()
            return
        for table_name, required_columns in SKILL_TABLE_CONTRACTS.items():
            self._ensure_contract(cur, table_name=table_name, required_columns=required_columns)

    def ensure_agent_tables(self, cur) -> None:
        if not self._runtime_schema_bootstrap_active:
            self.ensure_runtime_schema_bootstrapped()
            return
        for table_name, required_columns in AGENT_TABLE_CONTRACTS.items():
            self._ensure_contract(cur, table_name=table_name, required_columns=required_columns)

    def ensure_evaluator_tables(self, cur) -> None:
        if not self._runtime_schema_bootstrap_active:
            self.ensure_runtime_schema_bootstrapped()
            return
        self.ensure_agent_tables(cur)
        self._ensure_contract(
            cur,
            table_name="evaluator_runs",
            required_columns=EVALUATOR_RUNS_REQUIRED_COLUMNS,
        )

    def ensure_sessions_base_table(self, cur) -> None:
        self._ensure_contract(cur, table_name="sessions", required_columns=SESSION_TABLE_CONTRACTS["sessions"])

    def ensure_sessions_tables(self, cur) -> None:
        for table_name, required_columns in SESSION_TABLE_CONTRACTS.items():
            self._ensure_contract(cur, table_name=table_name, required_columns=required_columns)
