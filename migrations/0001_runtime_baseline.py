from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "apps" / "api"
for path in (ROOT, API_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from access_control import ensure_access_actors_table, ensure_access_quotas_table
from governance_helpers import ensure_model_providers_table, ensure_model_routes_table, ensure_tool_registry_table
from main import (
    ensure_agent_tables,
    ensure_audit_logs_table,
    ensure_change_requests_table,
    ensure_evaluator_tables,
    ensure_runtime_core_tables,
    ensure_sessions_tables,
    ensure_skill_registry_tables,
    ensure_trace_tables,
)
from risk_policy_helpers import ensure_risk_policies_table


MIGRATION_ID = "0001_runtime_baseline"
DESCRIPTION = "Create the baseline runtime schema for tasks, governance, session memory, agents, evaluators, traces, and change requests."


def apply(cur) -> None:
    ensure_runtime_core_tables(cur)
    ensure_sessions_tables(cur)
    ensure_audit_logs_table(cur)
    ensure_trace_tables(cur)
    ensure_skill_registry_tables(cur)
    ensure_agent_tables(cur)
    ensure_evaluator_tables(cur)
    ensure_change_requests_table(cur)
    ensure_risk_policies_table(cur)
    ensure_access_actors_table(cur)
    ensure_access_quotas_table(cur)
    ensure_tool_registry_table(cur)
    ensure_model_providers_table(cur)
    ensure_model_routes_table(cur)
