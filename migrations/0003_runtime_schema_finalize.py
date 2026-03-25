from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "apps" / "api"
WORKER_DIR = ROOT / "apps" / "worker"
for path in (ROOT, API_DIR, WORKER_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from access_control import ensure_access_actors_table, ensure_access_quotas_table
from governance_helpers import ensure_model_providers_table, ensure_model_routes_table, ensure_tool_registry_table
from schema_runtime import ApiSchemaRuntime
from governance_runtime import (
    ensure_model_providers_table as ensure_worker_model_providers_table,
    ensure_model_routes_table as ensure_worker_model_routes_table,
    ensure_tool_registry_table as ensure_worker_tool_registry_table,
)


MIGRATION_ID = "0003_runtime_schema_finalize"
DESCRIPTION = "Finalize stable runtime schema columns under migration-first flow."


def apply(cur) -> None:
    runtime = ApiSchemaRuntime(get_conn=lambda: None)

    runtime._runtime_core_schema_bootstrap_active = True
    runtime.ensure_runtime_core_tables(cur)
    runtime._runtime_core_schema_bootstrap_active = False

    runtime.ensure_change_requests_table(cur)

    runtime._stage56_schema_bootstrap_active = True
    runtime.ensure_agent_tables(cur)
    runtime.ensure_evaluator_tables(cur)
    runtime._stage56_schema_bootstrap_active = False

    ensure_access_actors_table(cur)
    ensure_access_quotas_table(cur)
    ensure_tool_registry_table(cur)
    ensure_model_routes_table(cur)
    ensure_model_providers_table(cur)
    ensure_worker_tool_registry_table(
        cur,
        runtime_schema_bootstrap_active=True,
        ensure_runtime_schema_bootstrapped=lambda: None,
    )
    ensure_worker_model_routes_table(
        cur,
        runtime_schema_bootstrap_active=True,
        ensure_runtime_schema_bootstrapped=lambda: None,
    )
    ensure_worker_model_providers_table(
        cur,
        runtime_schema_bootstrap_active=True,
        ensure_runtime_schema_bootstrapped=lambda: None,
    )
