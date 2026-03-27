from __future__ import annotations

from apps.api.schemas import TaskCreate


def confirm_draft(
    *,
    user_input: str,
    route: str,
    session_id: int | None = None,
    skill_id: str | None = None,
    skill_version: str | None = None,
    skill_args: dict | None = None,
    memory_context: dict | None = None,
) -> TaskCreate:
    return TaskCreate(
        user_input=user_input,
        session_id=session_id,
        skill_id=skill_id,
        skill_version=skill_version,
        skill_args=skill_args,
        intake_mode=route,
        draft_route=route,
        memory_context=memory_context,
    )
