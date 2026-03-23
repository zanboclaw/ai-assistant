from __future__ import annotations

from typing import Any


CLARIFICATION_PROMPT_PREAMBLE = (
    "以下补充信息已经提供完整，请直接基于这些信息完成任务，"
    "不要再输出“请提供以下信息”“请补充”等追问语句。"
)


def strip_legacy_clarification_suffix(user_input: str) -> str:
    raw = str(user_input or "").strip()
    if not raw:
        return ""
    marker = "\n\n补充说明：\n"
    if marker in raw:
        return raw.split(marker, 1)[0].strip()
    return raw


def normalize_task_clarification_history(value: Any) -> list[dict[str, str]]:
    items = value if isinstance(value, list) else []
    history: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        clarification = str(item.get("clarification") or "").strip()
        if not clarification:
            continue
        history.append(
            {
                "clarification": clarification[:4000],
                "note": str(item.get("note") or "").strip()[:400],
                "created_at": str(item.get("created_at") or "").strip()[:64],
            }
        )
    return history


def extract_task_clarification_state(
    runtime_overrides: dict[str, Any],
    *,
    fallback_user_input: str,
) -> tuple[str, list[dict[str, str]]]:
    overrides = dict(runtime_overrides or {})
    state = overrides.get("clarification_state") or {}
    if not isinstance(state, dict):
        state = {}

    original_user_input = str(state.get("original_user_input") or "").strip()
    if not original_user_input:
        original_user_input = strip_legacy_clarification_suffix(fallback_user_input)

    history = normalize_task_clarification_history(state.get("history"))
    return original_user_input, history


def build_clarified_user_input(
    original_user_input: str,
    clarification_history: list[dict[str, str]],
) -> str:
    base_input = str(original_user_input or "").strip()
    history = normalize_task_clarification_history(clarification_history)
    if not history:
        return base_input

    clarification_blocks: list[str] = [CLARIFICATION_PROMPT_PREAMBLE]
    for index, item in enumerate(history, start=1):
        block_lines = [f"第 {index} 次补充：", item["clarification"]]
        note = str(item.get("note") or "").strip()
        if note:
            block_lines.append(f"备注：{note}")
        created_at = str(item.get("created_at") or "").strip()
        if created_at:
            block_lines.append(f"补充时间：{created_at}")
        clarification_blocks.append("\n".join(block_lines))

    clarification_text = "\n\n".join(clarification_blocks)
    return f"{base_input}\n\n补充说明：\n{clarification_text}" if base_input else clarification_text


def build_task_display_user_input(
    raw_user_input: str,
    runtime_overrides: dict[str, Any] | None,
) -> str:
    original_user_input, clarification_history = extract_task_clarification_state(
        runtime_overrides or {},
        fallback_user_input=raw_user_input,
    )
    base_input = str(original_user_input or raw_user_input or "").strip()
    clarification_count = len(clarification_history)
    if clarification_count <= 0:
        return base_input
    return f"{base_input}（已补充澄清 {clarification_count} 次）"


def strip_artifact_suffix(text: str) -> str:
    return str(text or "").split("\n\n产出文件：", 1)[0].strip()


def build_task_summary_memory_content(task_display_input: str, final_result: str) -> str:
    normalized_result = strip_artifact_suffix(final_result)
    if len(normalized_result) > 1200:
        normalized_result = normalized_result[:1200].rstrip() + "..."
    return f"任务：{task_display_input.strip()}\n\n结果摘要：\n{normalized_result}"


def build_task_fact_memory_content(final_result: str) -> str:
    normalized_result = " ".join(strip_artifact_suffix(final_result).split())
    return normalized_result[:300].strip()
