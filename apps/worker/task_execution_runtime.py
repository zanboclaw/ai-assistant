from __future__ import annotations

from typing import Any, Optional


def run_legacy_plan(
    *,
    cur,
    task_id: int,
    user_input: str,
    step_names: list[str],
    existing_rows: list[dict[str, Any]],
    model_route_overrides: dict[str, dict[str, Any]] | None,
    create_legacy_steps,
    maybe_initialize_task_runtime_agent_records,
    start_step_execution,
    run_legacy_step,
    record_legacy_step_result,
    persist_legacy_step_runtime_state,
    maybe_dispatch_task_runtime_specialists,
):
    if not existing_rows:
        create_legacy_steps(cur, task_id, step_names)
        cur.connection.commit()

    maybe_initialize_task_runtime_agent_records(cur, task_id, user_input)
    cur.connection.commit()

    previous_outputs: list[str] = []
    step_outputs: list[str] = []

    for step_order, step_name in enumerate(step_names, start=1):
        start_step_execution(cur, task_id, step_order)

        output_text, ok = run_legacy_step(
            step_name,
            user_input,
            previous_outputs,
            model_route_overrides=model_route_overrides,
        )
        record_legacy_step_result(cur, task_id, step_order, output_text, ok)

        if not ok:
            raise RuntimeError(f"Step {step_order} failed: {output_text}")

        previous_outputs.append(output_text)
        persist_legacy_step_runtime_state(cur, task_id, user_input, step_order, output_text, step_outputs)
        maybe_dispatch_task_runtime_specialists(task_id, reason=f"legacy_step_{step_order}")

    return step_outputs, {}, {}


def select_task_plan_source(
    *,
    cur,
    task_id: int,
    user_input: str,
    skill_invocation: dict[str, Any] | None,
    task_intent: dict[str, Any] | None,
    deliverable_spec: dict[str, Any] | None,
    model_route_overrides: dict[str, dict[str, Any]] | None,
    get_task_steps,
    build_structured_steps_from_rows,
    update_task_trace_status,
    load_skill_definition,
    extract_skill_arg_keys,
    create_skill_trace,
    build_skill_plan,
    complete_skill_trace,
    build_deliverable_first_plan,
    resolve_task_plan_source,
    append_execution_result_closure_steps,
):
    existing_rows = get_task_steps(cur, task_id)
    if existing_rows and any(row.get("tool_name") for row in existing_rows):
        planned = build_structured_steps_from_rows(existing_rows)
        update_task_trace_status(cur, task_id, status="running", plan_source="existing_rows")
        return {
            "existing_rows": existing_rows,
            "planned": planned,
            "plan_source": "existing_rows",
            "execution_mode": "structured",
        }
    if existing_rows:
        planned = [row.get("step_name") or f"步骤 {row['step_order']}" for row in existing_rows]
        update_task_trace_status(cur, task_id, status="running", plan_source="existing_rows")
        return {
            "existing_rows": existing_rows,
            "planned": planned,
            "plan_source": "existing_rows",
            "execution_mode": "legacy",
        }

    if skill_invocation and str(skill_invocation.get("skill_id") or "").strip():
        skill_id = str(skill_invocation.get("skill_id") or "").strip()
        skill_version = str(skill_invocation.get("skill_version") or "").strip() or None
        skill_args = skill_invocation.get("skill_args") if isinstance(skill_invocation.get("skill_args"), dict) else {}
        skill_trace_id = None
        try:
            skill_definition = load_skill_definition(skill_id, skill_version)
            skill_arg_keys = extract_skill_arg_keys(skill_definition)
            skill_trace_id = create_skill_trace(
                cur,
                task_id=task_id,
                skill_id=skill_definition["skill_id"],
                skill_version=skill_definition["version"],
                input_snapshot={"user_input": user_input, "skill_args": skill_args},
                metadata={
                    "entrypoint_kind": skill_definition["entrypoint_kind"],
                    "display_name": skill_definition.get("display_name") or skill_definition["skill_id"],
                    "arg_keys": skill_arg_keys,
                    "provided_arg_keys": sorted(skill_args.keys()),
                },
            )
            planned = build_skill_plan(skill_definition, user_input=user_input, skill_args=skill_args)
            complete_skill_trace(
                cur,
                skill_trace_id=skill_trace_id,
                status="completed",
                output_snapshot={
                    "step_count": len(planned),
                    "skill_id": skill_definition["skill_id"],
                    "version": skill_definition["version"],
                    "step_titles": [str(item.get("step_name") or item.get("title") or f"步骤 {index + 1}") for index, item in enumerate(planned)],
                    "tool_names": [str(item.get("tool_name") or item.get("tool") or "") for item in planned],
                },
            )
            update_task_trace_status(cur, task_id, status="running", plan_source="explicit_skill")
            return {
                "existing_rows": [],
                "planned": planned,
                "plan_source": "explicit_skill",
                "execution_mode": "structured",
            }
        except Exception as exc:
            complete_skill_trace(
                cur,
                skill_trace_id=skill_trace_id,
                status="failed",
                output_snapshot={},
                error_summary=str(exc),
            )
            raise

    deliverable_first_plan = build_deliverable_first_plan(
        user_input,
        task_intent=task_intent or {},
        deliverable_spec=deliverable_spec or {},
    )
    if deliverable_first_plan:
        update_task_trace_status(cur, task_id, status="running", plan_source="deliverable_policy")
        return {
            "existing_rows": [],
            "planned": deliverable_first_plan,
            "plan_source": "deliverable_policy",
            "execution_mode": "structured",
        }

    planned, resolved_plan_source = resolve_task_plan_source(
        user_input,
        model_route_overrides=model_route_overrides,
    )
    deliverable_type = str((deliverable_spec or {}).get("deliverable_type") or "").strip()
    if (
        deliverable_type == "execution_result"
        and planned
        and isinstance(planned, list)
        and isinstance(planned[0], dict)
    ):
        planned = append_execution_result_closure_steps(
            planned,
            user_input=user_input,
            task_intent=task_intent or {},
            deliverable_spec=deliverable_spec or {},
        )
        resolved_plan_source = f"{resolved_plan_source}+execution_closure"
    execution_mode = "structured" if planned and isinstance(planned[0], dict) else "legacy"
    update_task_trace_status(cur, task_id, status="running", plan_source=resolved_plan_source)
    return {
        "existing_rows": [],
        "planned": planned,
        "plan_source": resolved_plan_source,
        "execution_mode": execution_mode,
    }


def prepare_executor_context(
    *,
    cur,
    task_id: int,
    user_input: str,
    plan_selection: dict[str, Any],
    create_structured_steps,
    get_task_steps,
    build_structured_steps_from_rows,
    hydrate_contexts_from_steps,
    persist_task_runtime_state,
    maybe_initialize_task_runtime_agent_records,
):
    existing_rows = plan_selection["existing_rows"]
    planned = plan_selection["planned"]
    execution_mode = plan_selection["execution_mode"]
    if execution_mode == "structured":
        if not existing_rows:
            create_structured_steps(cur, task_id, planned)
            cur.connection.commit()
            existing_rows = get_task_steps(cur, task_id)
            planned = build_structured_steps_from_rows(existing_rows)
        step_context, var_context, step_outputs = hydrate_contexts_from_steps(planned)
        persist_task_runtime_state(
            cur,
            task_id,
            user_input,
            status="running",
            current_step=None,
            step_context=step_context,
            var_context=var_context,
            step_outputs=step_outputs,
            task_error_message=None,
            checkpoint_error="",
            update_status_row=False,
        )
        maybe_initialize_task_runtime_agent_records(cur, task_id, user_input)
        cur.connection.commit()
        return step_context, var_context, step_outputs, execution_mode

    return {}, {}, [], execution_mode


def run_planned_execution(
    *,
    cur,
    task_id: int,
    user_input: str,
    plan_selection: dict[str, Any],
    claim_heartbeat: Optional[Any],
    model_route_overrides: dict[str, dict[str, Any]] | None,
    prepare_executor_context_fn,
    get_task_steps,
    build_structured_steps_from_rows,
    run_structured_step,
    maybe_dispatch_task_runtime_specialists,
    fallback_legacy_steps,
    run_legacy_plan_fn,
):
    step_context, var_context, step_outputs, execution_mode = prepare_executor_context_fn(
        cur=cur,
        task_id=task_id,
        user_input=user_input,
        plan_selection=plan_selection,
    )
    planned = plan_selection["planned"]

    if execution_mode == "structured":
        if not planned or not isinstance(planned[0], dict) or not planned[0].get("id"):
            planned = build_structured_steps_from_rows(get_task_steps(cur, task_id))
        for step in planned:
            step_executed = run_structured_step(
                cur,
                task_id,
                user_input,
                step,
                step_context,
                var_context,
                step_outputs,
                claim_heartbeat,
                model_route_overrides,
            )
            if step_executed:
                maybe_dispatch_task_runtime_specialists(task_id, reason=f"structured_step_{int(step.get('step_order') or 0)}")
        return step_outputs, step_context, var_context

    step_names = planned if isinstance(planned, list) else fallback_legacy_steps(user_input)
    return run_legacy_plan_fn(
        cur=cur,
        task_id=task_id,
        user_input=user_input,
        step_names=step_names,
        existing_rows=plan_selection["existing_rows"],
        model_route_overrides=model_route_overrides,
    )
