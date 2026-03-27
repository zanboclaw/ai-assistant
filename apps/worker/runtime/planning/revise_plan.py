from __future__ import annotations


def revise_plan(existing_plan: list[dict], *, recovery_reason: str) -> list[dict]:
    revised = [dict(item) for item in existing_plan]
    if revised:
        revised[0]["recovery_reason"] = recovery_reason
    return revised

