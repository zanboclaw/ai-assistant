from __future__ import annotations


def build_quota_status(quota_row: dict, usage_row: dict | None = None) -> dict:
    return {
        "quota": quota_row,
        "usage": usage_row or {},
    }

