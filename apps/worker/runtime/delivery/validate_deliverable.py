from __future__ import annotations

from typing import Any, Callable

from apps.worker.deliverable_runtime import evaluate_task_deliverable


def fetch_task_validation_context(
    cur,
    task_id: int,
    *,
    parse_jsonish: Callable[[Any, Any], Any],
    normalize_runtime_overrides: Callable[[Any], dict[str, Any]],
) -> dict[str, Any]:
    cur.execute(
        """
        SELECT task_intent_json, deliverable_spec_json, runtime_overrides
        FROM task_runs
        WHERE id = %s;
        """,
        (task_id,),
    )
    task_row = cur.fetchone() or {}
    task_intent = parse_jsonish(task_row.get("task_intent_json"), {}) or {}
    deliverable_spec = parse_jsonish(task_row.get("deliverable_spec_json"), {}) or {}
    runtime_overrides = normalize_runtime_overrides(task_row.get("runtime_overrides"))
    return {
        "task_intent": task_intent if isinstance(task_intent, dict) else {},
        "deliverable_spec": deliverable_spec if isinstance(deliverable_spec, dict) else {},
        "runtime_overrides": runtime_overrides,
    }


def validate_task_deliverable(
    cur,
    task_id: int,
    *,
    user_input: str,
    final_result: str,
    fetch_task_validation_context_fn: Callable[[Any, int], dict[str, Any]],
    evaluate_task_deliverable_fn: Callable[..., tuple[dict[str, Any], dict[str, Any]]] = evaluate_task_deliverable,
) -> tuple[dict[str, Any], dict[str, Any]]:
    task_context = fetch_task_validation_context_fn(cur, task_id)
    return evaluate_task_deliverable_fn(
        task_intent=task_context["task_intent"],
        deliverable_spec=task_context["deliverable_spec"],
        runtime_overrides=task_context["runtime_overrides"],
        user_input=user_input,
        final_result=final_result,
    )


__all__ = ["evaluate_task_deliverable", "fetch_task_validation_context", "validate_task_deliverable"]
