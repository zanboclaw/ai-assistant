from __future__ import annotations

from typing import Any
try:
    from typing import NotRequired, TypedDict
except ImportError:  # pragma: no cover - python<3.11 compatibility
    from typing_extensions import NotRequired, TypedDict


class StructuredStepExecutionState(TypedDict):
    execution_request: dict[str, Any]
    retry_count: int
    max_retries: int
    step_trace_id: NotRequired[int | None]
    tool_trace_id: NotRequired[int | None]


def execute_prepared_step_request(
    cur,
    task_id: int,
    user_input: str,
    step: dict,
    execution_request,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    claim_heartbeat,
    model_route_overrides,
    *,
    record_skipped_step,
    enforce_step_approval,
    execute_step_with_retries,
    step_trace_id: int | None = None,
    tool_trace_id: int | None = None,
):
    step_order = int(execution_request["step_order"])
    tool_name = str(execution_request["tool_name"])
    raw_input = execution_request["raw_input"]
    run_if = execution_request["run_if"]
    skip_if = execution_request["skip_if"]
    error_strategy = str(execution_request["error_strategy"])
    should_run = bool(execution_request["should_run"])
    skip_reason = str(execution_request["skip_reason"])
    max_retries = int(execution_request["effective_max_retries"])
    retry_count = int(execution_request["effective_retry_count"])

    if not should_run:
        record_skipped_step(
            cur,
            task_id,
            step_order,
            tool_name,
            raw_input,
            run_if,
            skip_if,
            skip_reason,
            error_strategy,
            user_input,
            step_context,
            var_context,
            step_outputs,
            step_trace_id=step_trace_id,
            tool_trace_id=tool_trace_id,
        )
        return None, retry_count

    resolved_input = execution_request["resolved_input"]
    enforce_step_approval(
        cur,
        task_id,
        step_order,
        step,
        tool_name,
        resolved_input,
        user_input,
        step_context,
        var_context,
        step_outputs,
        step_trace_id=step_trace_id,
        tool_trace_id=tool_trace_id,
        approval_required=bool(execution_request["approval_required"]),
        approval_reason=str(execution_request["approval_reason"]),
    )
    result, retry_count = execute_step_with_retries(
        cur,
        task_id,
        step_order,
        tool_name,
        resolved_input,
        step_context,
        var_context,
        max_retries,
        retry_count,
        claim_heartbeat,
        user_input,
        step_outputs,
        model_route_overrides=model_route_overrides,
    )
    return result, retry_count


def route_structured_step_outcome(
    cur,
    task_id: int,
    user_input: str,
    execution_request,
    result: dict,
    retry_count: int,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    *,
    logger,
    finalize_structured_step_success,
    finalize_structured_step_continue,
    step_trace_id: int | None = None,
    tool_trace_id: int | None = None,
):
    step_order = int(execution_request["step_order"])
    tool_name = str(execution_request["tool_name"])
    error_strategy = str(execution_request["error_strategy"])
    resolved_input = execution_request["resolved_input"]
    ok = bool(result["ok"])
    status = "completed" if ok else "failed"

    logger.info(
        "step finished task_id=%s step_order=%s tool=%s status=%s retry_count=%s",
        task_id,
        step_order,
        tool_name,
        status,
        retry_count,
    )

    if ok:
        finalize_structured_step_success(
            cur,
            task_id,
            step_order,
            tool_name,
            resolved_input,
            error_strategy,
            result,
            retry_count,
            user_input,
            step_context,
            var_context,
            step_outputs,
            step_trace_id=step_trace_id,
            tool_trace_id=tool_trace_id,
        )
        return

    if error_strategy == "continue":
        finalize_structured_step_continue(
            cur,
            task_id,
            step_order,
            tool_name,
            resolved_input,
            error_strategy,
            result,
            user_input,
            step_context,
            var_context,
            step_outputs,
            step_trace_id=step_trace_id,
            tool_trace_id=tool_trace_id,
        )
        return

    raise RuntimeError(f"Step {step_order} failed: {result['error']}")


def persist_structured_step_runtime_state(
    cur,
    task_id: int,
    user_input: str,
    step_order: int,
    runtime_status: str,
    output_payload: str,
    output_data: Any,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    checkpoint_error: str,
    update_var: bool,
    *,
    write_checkpoint,
):
    step_context[step_order] = {
        "output_payload": output_payload,
        "output_data": output_data,
    }
    if update_var and isinstance(output_data, dict):
        var_name = output_data.get("name")
        if isinstance(var_name, str) and var_name.strip():
            var_context[var_name.strip()] = output_data.get("value")
    step_outputs.append(output_payload)
    write_checkpoint(
        cur,
        task_id,
        user_input,
        runtime_status,
        step_order,
        step_context,
        var_context,
        step_outputs,
        checkpoint_error,
    )
    cur.connection.commit()


def persist_structured_step_outcome(
    cur,
    task_id: int,
    step_order: int,
    tool_name: str | None,
    input_payload: Any,
    step_status: str,
    output_payload: str,
    output_data: Any,
    error_message: str,
    error_strategy: str,
    user_input: str,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    checkpoint_error: str,
    update_var: bool,
    *,
    set_step_result,
    set_step_retry_count,
    persist_structured_step_runtime_state_fn,
    runtime_status: str = "running",
    retry_count: int | None = None,
):
    set_step_result(
        cur,
        task_id,
        step_order,
        status=step_status,
        tool_name=tool_name,
        input_payload=input_payload,
        output_payload=output_payload,
        output_data=output_data,
        error_message=error_message,
        error_strategy=error_strategy,
    )
    cur.connection.commit()

    if retry_count:
        set_step_retry_count(cur, task_id, step_order, retry_count)
        cur.connection.commit()

    persist_structured_step_runtime_state_fn(
        cur,
        task_id,
        user_input,
        step_order,
        runtime_status,
        output_payload,
        output_data,
        step_context,
        var_context,
        step_outputs,
        checkpoint_error,
        update_var,
    )


def finalize_structured_step_success(
    cur,
    task_id: int,
    step_order: int,
    tool_name: str,
    resolved_input: Any,
    error_strategy: str,
    result: dict,
    retry_count: int,
    user_input: str,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    *,
    persist_structured_step_outcome_fn,
    complete_step_and_tool_trace,
    step_trace_id: int | None = None,
    tool_trace_id: int | None = None,
):
    persist_structured_step_outcome_fn(
        cur,
        task_id,
        step_order,
        tool_name,
        resolved_input,
        "completed",
        result["output_text"],
        result["output_data"],
        "",
        error_strategy,
        user_input,
        step_context,
        var_context,
        step_outputs,
        checkpoint_error="",
        update_var=(tool_name == "set_var"),
        retry_count=retry_count,
    )
    complete_step_and_tool_trace(
        cur,
        step_trace_id=step_trace_id,
        tool_trace_id=tool_trace_id,
        status="completed",
        output_payload=result["output_text"],
        output_data=result["output_data"],
        retry_count=retry_count,
    )


def finalize_structured_step_continue(
    cur,
    task_id: int,
    step_order: int,
    tool_name: str,
    resolved_input: Any,
    error_strategy: str,
    result: dict,
    user_input: str,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    *,
    persist_structured_step_outcome_fn,
    complete_step_and_tool_trace,
    step_trace_id: int | None = None,
    tool_trace_id: int | None = None,
):
    persist_structured_step_outcome_fn(
        cur,
        task_id,
        step_order,
        tool_name,
        resolved_input,
        "failed",
        result["output_text"],
        result["output_data"],
        result["error"],
        error_strategy,
        user_input,
        step_context,
        var_context,
        step_outputs,
        checkpoint_error=result["error"],
        update_var=False,
    )
    complete_step_and_tool_trace(
        cur,
        step_trace_id=step_trace_id,
        tool_trace_id=tool_trace_id,
        status="failed",
        output_payload=result["output_text"],
        output_data=result["output_data"],
        error_summary=result["error"],
    )


def record_structured_step_exception(
    cur,
    task_id: int,
    step_order: int,
    tool_name: str,
    input_payload: Any,
    error_strategy: str,
    user_input: str,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    err: str,
    *,
    persist_structured_step_outcome_fn,
):
    persist_structured_step_outcome_fn(
        cur,
        task_id,
        step_order,
        tool_name,
        input_payload,
        "failed",
        err,
        None,
        err,
        error_strategy,
        user_input,
        step_context,
        var_context,
        step_outputs,
        checkpoint_error=err,
        update_var=False,
        runtime_status="failed",
    )


def record_skipped_step(
    cur,
    task_id: int,
    step_order: int,
    tool_name: str,
    raw_input: Any,
    run_if: Any,
    skip_if: Any,
    skip_reason: str,
    error_strategy: str,
    user_input: str,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    *,
    persist_structured_step_outcome_fn,
    complete_step_and_tool_trace,
    step_trace_id: int | None = None,
    tool_trace_id: int | None = None,
):
    skipped_output = f"步骤跳过：{skip_reason}"
    skipped_data = {
        "skipped": True,
        "reason": skip_reason,
        "run_if": run_if,
        "skip_if": skip_if,
    }
    persist_structured_step_outcome_fn(
        cur,
        task_id,
        step_order,
        tool_name,
        raw_input,
        "completed",
        skipped_output,
        skipped_data,
        "",
        error_strategy,
        user_input,
        step_context,
        var_context,
        step_outputs,
        checkpoint_error="",
        update_var=False,
    )
    complete_step_and_tool_trace(
        cur,
        step_trace_id=step_trace_id,
        tool_trace_id=tool_trace_id,
        status="completed",
        output_payload=skipped_output,
        output_data=skipped_data,
    )


def begin_structured_step_execution(
    cur,
    task_id: int,
    user_input: str,
    step: dict,
    execution_request,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    claim_heartbeat,
    *,
    logger,
    get_task_control_status,
    interrupt_task_if_requested,
    start_step_execution,
    create_step_and_tool_trace,
    set_current_trace_context,
):
    step_order = int(execution_request["step_order"])
    if claim_heartbeat is not None:
        claim_heartbeat.assert_owned()

    if get_task_control_status(task_id) == "interrupt_requested":
        interrupt_task_if_requested(cur, task_id, user_input, step_order, step_context, var_context, step_outputs)

    current_status = str(execution_request["current_status"])
    if current_status == "completed":
        return False, None, None
    if current_status == "failed":
        raise RuntimeError(f"Step {step_order} already failed")

    tool_name = str(execution_request["tool_name"])
    retry_count = int(execution_request["retry_count"])
    max_retries = int(execution_request["max_retries"])
    logger.info(
        "step starting task_id=%s step_order=%s tool=%s retry_count=%s max_retries=%s",
        task_id,
        step_order,
        tool_name,
        retry_count,
        max_retries,
    )
    start_step_execution(cur, task_id, step_order)
    step_trace_id, tool_trace_id = create_step_and_tool_trace(
        cur,
        task_id=task_id,
        task_step_id=int(step.get("id") or 0) or None,
        step_order=step_order,
        step_name=str(step.get("title") or f"步骤 {step_order}"),
        tool_name=tool_name,
        input_payload=execution_request["raw_input"],
        retry_count=retry_count,
        max_retries=max_retries,
    )
    set_current_trace_context(task_id=task_id, step_id=int(step.get("id") or 0) or None, step_trace_id=step_trace_id)
    return True, step_trace_id, tool_trace_id


def process_structured_step_request(
    cur,
    task_id: int,
    user_input: str,
    step: dict,
    execution_request,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    claim_heartbeat,
    model_route_overrides,
    *,
    supported_tools,
    ensure_tool_enabled,
    enrich_step_execution_request,
    execute_prepared_step_request_fn,
    step_trace_id: int | None = None,
    tool_trace_id: int | None = None,
):
    tool_name = str(execution_request["tool_name"])
    if tool_name not in supported_tools:
        raise ValueError(f"不支持的工具: {tool_name}")
    ensure_tool_enabled(tool_name)

    execution_request = enrich_step_execution_request(execution_request, step, step_context, var_context)
    result, retry_count = execute_prepared_step_request_fn(
        cur,
        task_id,
        user_input,
        step,
        execution_request,
        step_context,
        var_context,
        step_outputs,
        claim_heartbeat,
        model_route_overrides,
        step_trace_id=step_trace_id,
        tool_trace_id=tool_trace_id,
    )
    if result is None:
        return execution_request, None, int(execution_request["effective_retry_count"])
    return execution_request, result, retry_count


def build_structured_step_execution_state(execution_request) -> StructuredStepExecutionState:
    max_retries = execution_request.get("effective_max_retries", execution_request["max_retries"])
    retry_count = execution_request.get("effective_retry_count", execution_request["retry_count"])
    return {
        "execution_request": execution_request,
        "retry_count": int(retry_count),
        "max_retries": int(max_retries),
        "step_trace_id": None,
        "tool_trace_id": None,
    }


def update_structured_step_execution_state(
    execution_state: StructuredStepExecutionState,
    execution_request,
    retry_count: int,
) -> StructuredStepExecutionState:
    execution_state["execution_request"] = execution_request
    execution_state["retry_count"] = int(retry_count)
    execution_state["max_retries"] = int(
        execution_request.get("effective_max_retries", execution_request["max_retries"])
    )
    return execution_state


def perform_structured_step_execution(
    cur,
    task_id: int,
    user_input: str,
    step: dict,
    execution_state: StructuredStepExecutionState,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    claim_heartbeat,
    model_route_overrides,
    *,
    process_structured_step_request_fn,
):
    execution_request = execution_state["execution_request"]
    execution_request, result, retry_count = process_structured_step_request_fn(
        cur,
        task_id,
        user_input,
        step,
        execution_request,
        step_context,
        var_context,
        step_outputs,
        claim_heartbeat,
        model_route_overrides,
        step_trace_id=execution_state.get("step_trace_id"),
        tool_trace_id=execution_state.get("tool_trace_id"),
    )
    update_structured_step_execution_state(execution_state, execution_request, retry_count)
    return result


def handle_structured_step_exception(
    cur,
    task_id: int,
    user_input: str,
    execution_state: StructuredStepExecutionState,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    err: str,
    *,
    record_structured_step_exception,
    complete_step_and_tool_trace,
    step_trace_id: int | None = None,
    tool_trace_id: int | None = None,
):
    execution_request = execution_state["execution_request"]
    retry_count = int(execution_state["retry_count"])
    max_retries = int(execution_state["max_retries"])
    if retry_count:
        err = f"{err}（已重试 {retry_count}/{max_retries} 次）"
    record_structured_step_exception(
        cur,
        task_id,
        int(execution_request["step_order"]),
        str(execution_request["tool_name"]),
        execution_request["raw_input"],
        str(execution_request["error_strategy"]),
        user_input,
        step_context,
        var_context,
        step_outputs,
        err,
    )
    complete_step_and_tool_trace(
        cur,
        step_trace_id=step_trace_id,
        tool_trace_id=tool_trace_id,
        status="failed",
        output_payload=err,
        output_data=None,
        error_summary=err,
        retry_count=retry_count,
    )


def complete_structured_step_execution(
    cur,
    task_id: int,
    user_input: str,
    step: dict,
    execution_request,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    claim_heartbeat,
    model_route_overrides,
    *,
    process_structured_step_request_fn,
    route_structured_step_outcome_fn,
    record_structured_step_exception,
    complete_step_and_tool_trace,
    approval_required_exc_type,
    step_trace_id: int | None = None,
    tool_trace_id: int | None = None,
):
    execution_state = build_structured_step_execution_state(execution_request)
    execution_state["step_trace_id"] = step_trace_id
    execution_state["tool_trace_id"] = tool_trace_id

    try:
        result = perform_structured_step_execution(
            cur,
            task_id,
            user_input,
            step,
            execution_state,
            step_context,
            var_context,
            step_outputs,
            claim_heartbeat,
            model_route_overrides,
            process_structured_step_request_fn=process_structured_step_request_fn,
        )
        if result is None:
            return
    except approval_required_exc_type:
        raise
    except Exception as exc:
        handle_structured_step_exception(
            cur,
            task_id,
            user_input,
            execution_state,
            step_context,
            var_context,
            step_outputs,
            str(exc),
            record_structured_step_exception=record_structured_step_exception,
            complete_step_and_tool_trace=complete_step_and_tool_trace,
            step_trace_id=step_trace_id,
            tool_trace_id=tool_trace_id,
        )
        raise

    route_structured_step_outcome_fn(
        cur,
        task_id,
        user_input,
        execution_state["execution_request"],
        result,
        int(execution_state["retry_count"]),
        step_context,
        var_context,
        step_outputs,
        step_trace_id=step_trace_id,
        tool_trace_id=tool_trace_id,
    )


def run_structured_step(
    cur,
    task_id: int,
    user_input: str,
    step: dict,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    claim_heartbeat,
    model_route_overrides,
    *,
    normalize_step_execution_request,
    begin_structured_step_execution_fn,
    clear_current_trace_context,
    set_current_trace_context,
    complete_structured_step_execution,
):
    execution_request = normalize_step_execution_request(step)
    should_run, step_trace_id, tool_trace_id = begin_structured_step_execution_fn(
        cur,
        task_id,
        user_input,
        step,
        execution_request,
        step_context,
        var_context,
        step_outputs,
        claim_heartbeat,
    )
    if not should_run:
        return False

    clear_current_trace_context()
    set_current_trace_context(task_id=task_id, step_id=int(step.get("id") or 0) or None, step_trace_id=step_trace_id)
    try:
        complete_structured_step_execution(
            cur,
            task_id,
            user_input,
            step,
            execution_request,
            step_context,
            var_context,
            step_outputs,
            claim_heartbeat,
            model_route_overrides,
            step_trace_id=step_trace_id,
            tool_trace_id=tool_trace_id,
        )
    finally:
        clear_current_trace_context()
    return True
