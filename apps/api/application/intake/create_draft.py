from __future__ import annotations

from typing import Any

from apps.api.application.intake.analyze_input import analyze_input


def create_draft(cur, user_input: str, *, session_id: int | None = None, skill_id: str | None = None) -> dict[str, Any]:
    return analyze_input(cur, user_input, session_id=session_id, skill_id=skill_id)

