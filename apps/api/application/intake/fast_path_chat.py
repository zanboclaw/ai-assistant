from __future__ import annotations

from core.fast_path_runtime import build_fast_path_response


def fast_path_chat(cur, user_input: str, *, actor_name: str) -> dict:
    return build_fast_path_response(cur, user_input=user_input, actor_name=actor_name)

