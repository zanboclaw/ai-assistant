import json
from typing import Any

from fastapi import HTTPException

from core.schema_migration_runtime import is_schema_contract_ready
from core.runtime_defaults import get_default_risk_policy_entries
from json_utils import safe_json_dumps


DEFAULT_RISK_POLICIES = get_default_risk_policy_entries()
RISK_POLICY_MAP = {item["policy_key"]: item for item in DEFAULT_RISK_POLICIES}
RISK_POLICY_SCHEMA_MIGRATION_ID = "0011_api_governance_schema_finalize"
RISK_POLICY_REQUIRED_COLUMNS = (
    "id",
    "policy_key",
    "value_type",
    "policy_value",
    "description",
    "created_at",
    "updated_at",
)


def create_risk_policies_table(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS risk_policies (
            id SERIAL PRIMARY KEY,
            policy_key TEXT NOT NULL UNIQUE,
            value_type TEXT NOT NULL,
            policy_value TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def ensure_risk_policies_table(cur):
    if is_schema_contract_ready(
        cur,
        migration_id=RISK_POLICY_SCHEMA_MIGRATION_ID,
        table_name="risk_policies",
        required_columns=RISK_POLICY_REQUIRED_COLUMNS,
    ):
        return
    raise RuntimeError(
        "risk_policies schema is not ready. Please run `python3 scripts/run_migrations.py` before starting API."
    )


def seed_default_risk_policies(cur):
    ensure_risk_policies_table(cur)
    for item in DEFAULT_RISK_POLICIES:
        cur.execute(
            """
            INSERT INTO risk_policies (policy_key, value_type, policy_value, description)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (policy_key) DO NOTHING;
            """,
            (
                item["policy_key"],
                item["value_type"],
                safe_json_dumps(item["policy_value"]),
                item["description"],
            ),
        )


def deserialize_policy_row(row: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed_value = json.loads(row["policy_value"])
    except Exception:
        parsed_value = row["policy_value"]
    return {
        "policy_key": row["policy_key"],
        "value_type": row["value_type"],
        "policy_value": parsed_value,
        "description": row["description"],
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def validate_policy_value(policy_key: str, value: Any) -> tuple[str, str]:
    item = RISK_POLICY_MAP.get(policy_key)
    if not item:
        raise HTTPException(status_code=404, detail="Risk policy not found")

    value_type = item["value_type"]
    if value_type == "bool":
        if not isinstance(value, bool):
            raise HTTPException(status_code=400, detail="policy_value must be boolean")
    elif value_type == "json":
        if not isinstance(value, list) or not all(isinstance(part, str) and part.strip() for part in value):
            raise HTTPException(status_code=400, detail="policy_value must be a non-empty string list")
        value = [part.strip() for part in value]
    else:
        raise HTTPException(status_code=500, detail="Unsupported policy type")

    return value_type, safe_json_dumps(value)


def update_risk_policy_entry(
    cur,
    *,
    policy_key: str,
    value_type: str,
    serialized_value: str,
    policy_value: Any,
    actor_name: str,
    actor_role: str,
    seed_default_risk_policies_fn,
    insert_audit_log_fn,
    deserialize_policy_row_fn,
) -> dict[str, Any]:
    seed_default_risk_policies_fn(cur)
    cur.execute(
        """
        UPDATE risk_policies
        SET value_type = %s,
            policy_value = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE policy_key = %s
        RETURNING policy_key, value_type, policy_value, description, created_at, updated_at;
        """,
        (value_type, serialized_value, policy_key),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Risk policy not found")
    insert_audit_log_fn(
        cur,
        "risk.update",
        actor_name,
        None,
        {
            "policy_key": policy_key,
            "policy_value": policy_value,
            "role": actor_role,
        },
    )
    return deserialize_policy_row_fn(row)
