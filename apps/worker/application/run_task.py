from __future__ import annotations

from typing import Optional

from apps.worker.runtime.planning.build_execution_plan import build_execution_plan
from apps.worker.runtime.planning.build_intent_plan import build_intent_plan
from apps.worker.runtime.task_loading.load_task import load_task_runtime_context
from apps.worker.task_processing_runtime import process_task as process_task_impl
from apps.worker.worker_runtime_context import (
    ApprovalRequired,
    AutoRecoveryScheduled,
    ClaimLostError,
    InterruptRequested,
    augment_user_input_with_memory_context,
    augment_user_input_with_runtime_feedback,
    clear_current_trace_context,
    ensure_approvals_table,
    ensure_task_steps_columns,
    extract_deliverable_spec,
    extract_task_intent,
    extract_task_model_route_overrides,
    extract_task_skill_invocation,
    fail_task_for_missing_clarification,
    fetch_latest_evaluator_feedback,
    finalize_task_failure,
    finalize_task_success,
    get_conn,
    logger,
    maybe_dispatch_task_runtime_specialists,
    run_planned_execution,
    seed_default_model_providers,
    seed_default_model_routes,
    seed_default_tool_registry,
    select_task_plan_source,
    set_current_trace_context,
    start_task_execution,
)


def process_task(task: dict, claim_heartbeat: Optional[object] = None):
    return process_task_impl(
        task,
        claim_heartbeat,
        get_conn=get_conn,
        logger=logger,
        augment_user_input_with_memory_context=augment_user_input_with_memory_context,
        extract_task_model_route_overrides=extract_task_model_route_overrides,
        extract_task_skill_invocation=extract_task_skill_invocation,
        extract_task_intent=extract_task_intent,
        extract_deliverable_spec=extract_deliverable_spec,
        ensure_task_steps_columns=ensure_task_steps_columns,
        ensure_approvals_table=ensure_approvals_table,
        seed_default_tool_registry=seed_default_tool_registry,
        seed_default_model_providers=seed_default_model_providers,
        seed_default_model_routes=seed_default_model_routes,
        fetch_latest_evaluator_feedback=fetch_latest_evaluator_feedback,
        augment_user_input_with_runtime_feedback=augment_user_input_with_runtime_feedback,
        fail_task_for_missing_clarification=fail_task_for_missing_clarification,
        start_task_execution=start_task_execution,
        set_current_trace_context=set_current_trace_context,
        clear_current_trace_context=clear_current_trace_context,
        select_task_plan_source=select_task_plan_source,
        run_planned_execution=run_planned_execution,
        finalize_task_success=finalize_task_success,
        finalize_task_failure=finalize_task_failure,
        maybe_dispatch_task_runtime_specialists=maybe_dispatch_task_runtime_specialists,
        approval_required_exc_type=ApprovalRequired,
        interrupt_requested_exc_type=InterruptRequested,
        auto_recovery_scheduled_exc_type=AutoRecoveryScheduled,
        claim_lost_exc_type=ClaimLostError,
        load_task_runtime_context_fn=load_task_runtime_context,
        build_intent_plan_fn=build_intent_plan,
        build_execution_plan_fn=build_execution_plan,
    )

__all__ = ["process_task"]
