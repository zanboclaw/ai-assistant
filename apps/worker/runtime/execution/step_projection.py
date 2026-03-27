from __future__ import annotations

from typing import Any, Callable


def build_structured_steps_from_rows(
    rows: list[dict[str, Any]],
    *,
    parse_json_text: Callable[[Any, Any], Any],
) -> list[dict[str, Any]]:
    planned: list[dict[str, Any]] = []
    for row in rows:
        planned.append(
            {
                "id": int(row["id"]),
                "step_order": int(row["step_order"]),
                "title": str(row.get("step_name") or f"步骤 {row['step_order']}"),
                "tool": str(row.get("tool_name") or "").strip(),
                "input": parse_json_text(row.get("input_payload"), {}),
                "run_if": parse_json_text(row.get("run_if")),
                "skip_if": parse_json_text(row.get("skip_if")),
                "retry_count": int(row.get("retry_count") or 0),
                "max_retries": int(row.get("max_retries") or 0),
                "error_strategy": str(row.get("error_strategy") or "fail"),
                "status": str(row.get("status") or "pending"),
                "output_payload": row.get("output_payload"),
                "output_data": parse_json_text(row.get("output_data")),
            }
        )
    return planned


def hydrate_contexts_from_steps(steps: list[dict[str, Any]]) -> tuple[dict[int, dict[str, Any]], dict[str, Any], list[str]]:
    step_context: dict[int, dict[str, Any]] = {}
    var_context: dict[str, Any] = {}
    step_outputs: list[str] = []

    for step in steps:
        if step.get("status") != "completed":
            continue

        step_order = int(step["step_order"])
        output_payload = step.get("output_payload")
        output_data = step.get("output_data")
        step_context[step_order] = {
            "output_payload": output_payload,
            "output_data": output_data,
        }
        if isinstance(output_payload, str) and output_payload.strip():
            step_outputs.append(output_payload)

        if step.get("tool") == "set_var" and isinstance(output_data, dict):
            var_name = output_data.get("name")
            if isinstance(var_name, str) and var_name.strip():
                var_context[var_name.strip()] = output_data.get("value")

    return step_context, var_context, step_outputs


__all__ = [
    "build_structured_steps_from_rows",
    "hydrate_contexts_from_steps",
]
