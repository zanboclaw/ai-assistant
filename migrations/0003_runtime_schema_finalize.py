from __future__ import annotations

MIGRATION_ID = "0003_runtime_schema_finalize"
DESCRIPTION = "Compatibility marker for the retired Python runtime schema finalize migration."


def apply(cur) -> None:
    # The finalized runtime schema is now owned by db/migrations and enforced at
    # startup via contract checks instead of runtime DDL.
    return None
