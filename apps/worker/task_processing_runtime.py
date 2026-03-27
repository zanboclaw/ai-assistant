from __future__ import annotations

from typing import Any, Optional


def process_task(
    task: dict,
    claim_heartbeat,
    *,
    get_conn,
    logger,
    augment_user_input_with_memory_context,
    extract_task_model_route_overrides,
    extract_task_skill_invocation,
    extract_task_intent,
    extract_deliverable_spec,
    ensure_task_steps_columns,
    ensure_approvals_table,
    seed_default_tool_registry,
    seed_default_model_providers,
    seed_default_model_routes,
    fetch_latest_evaluator_feedback,
    augment_user_input_with_runtime_feedback,
    fail_task_for_missing_clarification,
    start_task_execution,
    set_current_trace_context,
    clear_current_trace_context,
    select_task_plan_source,
    run_planned_execution,
    finalize_task_success,
    finalize_task_failure,
    maybe_dispatch_task_runtime_specialists,
    approval_required_exc_type,
    interrupt_requested_exc_type,
    auto_recovery_scheduled_exc_type,
    claim_lost_exc_type,
    load_task_runtime_context_fn=None,
    build_intent_plan_fn=None,
    build_execution_plan_fn=None,
):
    runtime_context = (
        load_task_runtime_context_fn(task)
        if load_task_runtime_context_fn is not None
        else {
            "task": task,
            "task_id": task["id"],
            "user_input": task["user_input"],
            "task_intent": extract_task_intent(task),
            "deliverable_spec": extract_deliverable_spec(task),
            "model_route_overrides": extract_task_model_route_overrides(task),
            "skill_invocation": extract_task_skill_invocation(task),
        }
    )
    task_id = int(runtime_context["task_id"])
    user_input = str(runtime_context["user_input"])
    planner_user_input = augment_user_input_with_memory_context(user_input, runtime_context["task"])
    task_model_route_overrides = dict(runtime_context.get("model_route_overrides") or {})
    task_skill_invocation = dict(runtime_context.get("skill_invocation") or {})
    task_intent = dict(runtime_context.get("task_intent") or {})
    task_deliverable_spec = dict(runtime_context.get("deliverable_spec") or {})
    intent_plan = build_intent_plan_fn(runtime_context) if build_intent_plan_fn is not None else task_intent

    conn = get_conn()
    cur = conn.cursor()
    step_outputs: list[str] = []
    step_context: dict[int, dict] = {}
    var_context: dict[str, Any] = {}

    try:
        logger.info("task started id=%s user_input=%s", task_id, str(user_input)[:200])
        ensure_task_steps_columns(cur)
        ensure_approvals_table(cur)
        seed_default_tool_registry(cur)
        seed_default_model_providers(cur)
        seed_default_model_routes(cur)
        latest_evaluator = fetch_latest_evaluator_feedback(cur, task_id)
        planner_user_input = augment_user_input_with_runtime_feedback(planner_user_input, latest_evaluator)
        if bool(intent_plan.get("needs_clarification")) or bool(((task_deliverable_spec.get("clarify") or {}).get("blocking"))):
            fail_task_for_missing_clarification(
                cur,
                task_id,
                user_input,
                task_intent=intent_plan,
                deliverable_spec=task_deliverable_spec,
            )
            logger.info("task blocked pending clarification id=%s", task_id)
            return
        start_task_execution(cur, task_id, planner_user_input)

        set_current_trace_context(task_id=task_id)
        try:
            plan_selection = (
                build_execution_plan_fn(
                    cur,
                    task_id=task_id,
                    planner_user_input=planner_user_input,
                    task_context=runtime_context,
                    intent_plan=intent_plan,
                    select_task_plan_source=select_task_plan_source,
                )
                if build_execution_plan_fn is not None
                else select_task_plan_source(
                    cur,
                    task_id,
                    planner_user_input,
                    skill_invocation=task_skill_invocation,
                    task_intent=intent_plan,
                    deliverable_spec=task_deliverable_spec,
                    model_route_overrides=task_model_route_overrides,
                )
            )
        finally:
            clear_current_trace_context()
        step_outputs, step_context, var_context = run_planned_execution(
            cur,
            task_id,
            planner_user_input,
            plan_selection,
            claim_heartbeat,
            task_model_route_overrides,
        )

        finalize_task_success(
            cur,
            task_id,
            planner_user_input,
            step_outputs,
            step_context,
            var_context,
        )

    except approval_required_exc_type as exc:
        conn.commit()
        maybe_dispatch_task_runtime_specialists(task_id, reason="waiting_approval")
        logger.info("task paused for approval id=%s reason=%s", task_id, str(exc))
    except interrupt_requested_exc_type as exc:
        conn.commit()
        maybe_dispatch_task_runtime_specialists(task_id, reason="interrupt_requested")
        logger.info("task paused by interrupt id=%s reason=%s", task_id, str(exc))
    except auto_recovery_scheduled_exc_type as exc:
        conn.commit()
        logger.info("task auto recovery queued id=%s reason=%s", task_id, str(exc))
    except claim_lost_exc_type as exc:
        logger.warning("task stopped because claim was lost id=%s reason=%s", task_id, str(exc))
    except Exception as exc:
        finalize_task_failure(
            cur,
            task_id,
            planner_user_input,
            step_context,
            var_context,
            step_outputs,
            str(exc),
        )
        logger.exception("task failed id=%s error=%s", task_id, exc)
    finally:
        cur.close()
        conn.close()
