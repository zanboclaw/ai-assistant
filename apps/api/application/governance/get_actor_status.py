from __future__ import annotations


def build_actor_status(actor_row: dict, quota_usage: dict | None = None) -> dict:
    return {
        "actor": actor_row,
        "quota_usage": quota_usage or {},
    }

