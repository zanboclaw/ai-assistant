from __future__ import annotations

from functools import partial

from apps.worker.application.run_task import process_task
from apps.worker.deliverable_runtime import (
    build_clarification_required_recovery_action,
    build_clarification_required_validation_report,
    build_failed_recovery_action,
)
from apps.worker.runtime.agents.agent_selector import resolve_specialist_fanout_strategy as resolve_specialist_fanout_strategy_impl
from apps.worker.runtime.tools.tool_dispatcher import execute_tool
from apps.worker.runtime.tools.tool_registry import load_tool_registry_settings
from apps.worker.step_request_runtime import normalize_web_search_input as normalize_web_search_input_impl
from apps.worker.task_payloads import (
    extract_deliverable_spec,
    extract_task_intent,
    sanitize_web_search_query,
)
from apps.worker.worker_runtime_context import (
    AUTO_STAGE5_SPECIALIST_COUNT,
    fail_task_for_missing_clarification,
    main,
)

normalize_web_search_input = partial(
    normalize_web_search_input_impl,
    sanitize_web_search_query=sanitize_web_search_query,
)

resolve_specialist_fanout_strategy = partial(
    resolve_specialist_fanout_strategy_impl,
    extract_task_intent=extract_task_intent,
    extract_deliverable_spec=extract_deliverable_spec,
    auto_stage5_specialist_count=AUTO_STAGE5_SPECIALIST_COUNT,
)

WORKER_RUNTIME_EXPORTS = (
    "main",
    "process_task",
)

__all__ = [
    "WORKER_RUNTIME_EXPORTS",
    "build_clarification_required_recovery_action",
    "build_clarification_required_validation_report",
    "build_failed_recovery_action",
    "execute_tool",
    "fail_task_for_missing_clarification",
    "load_tool_registry_settings",
    "main",
    "normalize_web_search_input",
    "process_task",
    "resolve_specialist_fanout_strategy",
]
