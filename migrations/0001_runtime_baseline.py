from __future__ import annotations

MIGRATION_ID = "0001_runtime_baseline"
DESCRIPTION = "Compatibility marker for the retired Python runtime baseline migration."


def apply(cur) -> None:
    # The runtime baseline now lives in db/migrations/*.sql. We keep this
    # marker so existing environments still record the historical migration id.
    return None
