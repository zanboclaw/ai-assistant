import json
import threading

from fastapi import HTTPException

from core.schema_migration_runtime import is_schema_contract_ready
from core.runtime_defaults import (
    get_default_model_provider_entries,
    get_default_model_route_entries,
    get_default_tool_registry_entries,
)


DEFAULT_TOOL_REGISTRY = get_default_tool_registry_entries()
DEFAULT_MODEL_ROUTES = get_default_model_route_entries()
DEFAULT_MODEL_PROVIDERS = get_default_model_provider_entries()

_SCHEMA_FLAGS = {
    "tool_registry_entries": False,
    "model_routes": False,
    "model_providers": False,
}
_SCHEMA_LOCK = threading.Lock()
GOVERNANCE_SCHEMA_MIGRATION_ID = "0011_api_governance_schema_finalize"
TOOL_REGISTRY_REQUIRED_COLUMNS = (
    "tool_name",
    "enabled",
    "provider_type",
    "transport",
    "server_name",
    "provider_config",
    "risk_level",
    "approval_required",
    "description",
    "created_at",
    "updated_at",
)
MODEL_ROUTES_REQUIRED_COLUMNS = (
    "route_name",
    "provider",
    "model_name",
    "temperature",
    "max_tokens",
    "enabled",
    "description",
    "created_at",
    "updated_at",
)
MODEL_PROVIDERS_REQUIRED_COLUMNS = (
    "provider_name",
    "driver",
    "base_url",
    "api_key_env",
    "enabled",
    "description",
    "created_at",
    "updated_at",
)


def _mark_schema_ready(table_name: str):
    _SCHEMA_FLAGS[table_name] = True


def create_tool_registry_table(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS tool_registry_entries (
            tool_name TEXT PRIMARY KEY,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            provider_type TEXT NOT NULL DEFAULT 'builtin',
            transport TEXT NOT NULL DEFAULT 'local',
            server_name TEXT NOT NULL DEFAULT '',
            provider_config JSONB NOT NULL DEFAULT '{}'::jsonb,
            risk_level TEXT NOT NULL,
            approval_required BOOLEAN NOT NULL DEFAULT FALSE,
            description TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def create_model_routes_table(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS model_routes (
            route_name TEXT PRIMARY KEY,
            provider TEXT NOT NULL DEFAULT 'openai_compatible',
            model_name TEXT NOT NULL,
            temperature DOUBLE PRECISION NOT NULL,
            max_tokens INTEGER NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            description TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def create_model_providers_table(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS model_providers (
            provider_name TEXT PRIMARY KEY,
            driver TEXT NOT NULL DEFAULT 'openai_compatible',
            base_url TEXT NOT NULL,
            api_key_env TEXT NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            description TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def ensure_tool_registry_table(cur):
    if _SCHEMA_FLAGS["tool_registry_entries"]:
        return
    if is_schema_contract_ready(
        cur,
        migration_id=GOVERNANCE_SCHEMA_MIGRATION_ID,
        table_name="tool_registry_entries",
        required_columns=TOOL_REGISTRY_REQUIRED_COLUMNS,
    ):
        _mark_schema_ready("tool_registry_entries")
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_FLAGS["tool_registry_entries"]:
            return
        if is_schema_contract_ready(
            cur,
            migration_id=GOVERNANCE_SCHEMA_MIGRATION_ID,
            table_name="tool_registry_entries",
            required_columns=TOOL_REGISTRY_REQUIRED_COLUMNS,
        ):
            _mark_schema_ready("tool_registry_entries")
            return
        raise RuntimeError(
            "tool_registry_entries schema is not ready. Please run `python3 scripts/run_migrations.py` before starting API."
        )


def ensure_model_routes_table(cur):
    if _SCHEMA_FLAGS["model_routes"]:
        return
    if is_schema_contract_ready(
        cur,
        migration_id=GOVERNANCE_SCHEMA_MIGRATION_ID,
        table_name="model_routes",
        required_columns=MODEL_ROUTES_REQUIRED_COLUMNS,
    ):
        _mark_schema_ready("model_routes")
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_FLAGS["model_routes"]:
            return
        if is_schema_contract_ready(
            cur,
            migration_id=GOVERNANCE_SCHEMA_MIGRATION_ID,
            table_name="model_routes",
            required_columns=MODEL_ROUTES_REQUIRED_COLUMNS,
        ):
            _mark_schema_ready("model_routes")
            return
        raise RuntimeError(
            "model_routes schema is not ready. Please run `python3 scripts/run_migrations.py` before starting API."
        )


def ensure_model_providers_table(cur):
    if _SCHEMA_FLAGS["model_providers"]:
        return
    if is_schema_contract_ready(
        cur,
        migration_id=GOVERNANCE_SCHEMA_MIGRATION_ID,
        table_name="model_providers",
        required_columns=MODEL_PROVIDERS_REQUIRED_COLUMNS,
    ):
        _mark_schema_ready("model_providers")
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_FLAGS["model_providers"]:
            return
        if is_schema_contract_ready(
            cur,
            migration_id=GOVERNANCE_SCHEMA_MIGRATION_ID,
            table_name="model_providers",
            required_columns=MODEL_PROVIDERS_REQUIRED_COLUMNS,
        ):
            _mark_schema_ready("model_providers")
            return
        raise RuntimeError(
            "model_providers schema is not ready. Please run `python3 scripts/run_migrations.py` before starting API."
        )


def seed_default_tool_registry(cur):
    ensure_tool_registry_table(cur)
    for tool in DEFAULT_TOOL_REGISTRY:
        cur.execute(
            """
            INSERT INTO tool_registry_entries (tool_name, enabled, risk_level, description)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (tool_name) DO NOTHING;
            """,
            (tool["tool_name"], tool["enabled"], tool["risk_level"], tool["description"]),
        )


def seed_default_model_routes(cur):
    ensure_model_routes_table(cur)
    for route in DEFAULT_MODEL_ROUTES:
        cur.execute(
            """
            INSERT INTO model_routes (
                route_name, provider, model_name, temperature, max_tokens, enabled, description
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (route_name) DO NOTHING;
            """,
            (
                route["route_name"],
                route["provider"],
                route["model_name"],
                route["temperature"],
                route["max_tokens"],
                route["enabled"],
                route["description"],
            ),
        )


def seed_default_model_providers(cur):
    ensure_model_providers_table(cur)
    for provider in DEFAULT_MODEL_PROVIDERS:
        cur.execute(
            """
            INSERT INTO model_providers (
                provider_name, driver, base_url, api_key_env, enabled, description
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (provider_name) DO NOTHING;
            """,
            (
                provider["provider_name"],
                provider["driver"],
                provider["base_url"],
                provider["api_key_env"],
                provider["enabled"],
                provider["description"],
            ),
        )


def update_tool_registry_entry(
    cur,
    *,
    tool_name: str,
    enabled: bool,
    provider_type: str,
    transport: str,
    server_name: str,
    provider_config: dict,
    risk_level: str,
    approval_required: bool,
    description: str,
    actor_name: str,
    seed_default_tool_registry_fn,
    insert_audit_log_fn,
    serialize_tool_registry_row_fn,
) -> dict:
    seed_default_tool_registry_fn(cur)
    cur.execute(
        """
        INSERT INTO tool_registry_entries (
            tool_name,
            enabled,
            provider_type,
            transport,
            server_name,
            provider_config,
            risk_level,
            approval_required,
            description
        )
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
        ON CONFLICT (tool_name) DO UPDATE
        SET enabled = EXCLUDED.enabled,
            provider_type = EXCLUDED.provider_type,
            transport = EXCLUDED.transport,
            server_name = EXCLUDED.server_name,
            provider_config = EXCLUDED.provider_config,
            risk_level = EXCLUDED.risk_level,
            approval_required = EXCLUDED.approval_required,
            description = EXCLUDED.description,
            updated_at = CURRENT_TIMESTAMP
        RETURNING tool_name, enabled, provider_type, transport, server_name, provider_config, risk_level, approval_required, description, created_at, updated_at;
        """,
        (
            tool_name,
            enabled,
            provider_type,
            transport,
            server_name,
            json.dumps(provider_config, ensure_ascii=False),
            risk_level,
            approval_required,
            description,
        ),
    )
    row = cur.fetchone()
    insert_audit_log_fn(
        cur,
        "tool_registry.update",
        actor_name,
        None,
        {
            "tool_name": tool_name,
            "enabled": enabled,
            "provider_type": provider_type,
            "transport": transport,
            "server_name": server_name,
            "risk_level": risk_level,
            "approval_required": approval_required,
        },
    )
    return serialize_tool_registry_row_fn(row)


def update_model_route_entry(
    cur,
    *,
    route_name: str,
    provider: str,
    model_name: str,
    temperature: float,
    max_tokens: int,
    enabled: bool,
    description: str,
    actor_name: str,
    seed_default_model_providers_fn,
    seed_default_model_routes_fn,
    insert_audit_log_fn,
    serialize_model_route_row_fn,
) -> dict:
    seed_default_model_providers_fn(cur)
    seed_default_model_routes_fn(cur)
    cur.execute("SELECT provider_name FROM model_providers WHERE provider_name = %s;", (provider,))
    if not cur.fetchone():
        raise HTTPException(status_code=404, detail=f"Model provider not found: {provider}")
    cur.execute(
        """
        UPDATE model_routes
        SET provider = %s,
            model_name = %s,
            temperature = %s,
            max_tokens = %s,
            enabled = %s,
            description = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE route_name = %s
        RETURNING route_name, provider, model_name, temperature, max_tokens, enabled, description, created_at, updated_at;
        """,
        (
            provider,
            model_name,
            temperature,
            max_tokens,
            enabled,
            description,
            route_name,
        ),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Model route not found: {route_name}")
    insert_audit_log_fn(
        cur,
        "model_route.update",
        actor_name,
        None,
        {
            "route_name": route_name,
            "provider": provider,
            "model_name": model_name,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "enabled": enabled,
        },
    )
    return serialize_model_route_row_fn(row)


def upsert_model_provider_entry(
    cur,
    *,
    provider_name: str,
    driver: str,
    base_url: str,
    api_key_env: str,
    enabled: bool,
    description: str,
    actor_name: str,
    seed_default_model_providers_fn,
    insert_audit_log_fn,
    serialize_model_provider_row_fn,
) -> dict:
    seed_default_model_providers_fn(cur)
    cur.execute(
        """
        INSERT INTO model_providers (provider_name, driver, base_url, api_key_env, enabled, description)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (provider_name)
        DO UPDATE SET driver = EXCLUDED.driver,
                      base_url = EXCLUDED.base_url,
                      api_key_env = EXCLUDED.api_key_env,
                      enabled = EXCLUDED.enabled,
                      description = EXCLUDED.description,
                      updated_at = CURRENT_TIMESTAMP
        RETURNING provider_name, driver, base_url, api_key_env, enabled, description, created_at, updated_at;
        """,
        (
            provider_name,
            driver,
            base_url,
            api_key_env,
            enabled,
            description,
        ),
    )
    row = cur.fetchone()
    insert_audit_log_fn(
        cur,
        "model_provider.update",
        actor_name,
        None,
        {
            "provider_name": provider_name,
            "driver": driver,
            "base_url": base_url,
            "api_key_env": api_key_env,
            "enabled": enabled,
        },
    )
    return serialize_model_provider_row_fn(row)
