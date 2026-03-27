from __future__ import annotations

from core.task_runtime import strip_artifact_suffix


def build_final_response(result_text: str) -> str:
    return strip_artifact_suffix(result_text)

