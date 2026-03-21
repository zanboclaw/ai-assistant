import threading

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


def _table_exists(cur, table_name: str) -> bool:
    cur.execute("SELECT to_regclass(%s) AS regclass;", (f"public.{table_name}",))
    return bool(cur.fetchone()["regclass"])


def _mark_schema_ready(table_name: str):
    _SCHEMA_FLAGS[table_name] = True


def ensure_tool_registry_table(cur):
    if _SCHEMA_FLAGS["tool_registry_entries"]:
        return
    if _table_exists(cur, "tool_registry_entries"):
        _mark_schema_ready("tool_registry_entries")
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_FLAGS["tool_registry_entries"]:
            return
        if _table_exists(cur, "tool_registry_entries"):
            _mark_schema_ready("tool_registry_entries")
            return
        cur.execute("SELECT pg_advisory_xact_lock(hashtext('tool_registry_entries_schema'));")
        if _table_exists(cur, "tool_registry_entries"):
            _mark_schema_ready("tool_registry_entries")
            return
        cur.execute(
            """
            CREATE TABLE tool_registry_entries (
                tool_name TEXT PRIMARY KEY,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                risk_level TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        _mark_schema_ready("tool_registry_entries")


def ensure_model_routes_table(cur):
    if _SCHEMA_FLAGS["model_routes"]:
        return
    if _table_exists(cur, "model_routes"):
        _mark_schema_ready("model_routes")
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_FLAGS["model_routes"]:
            return
        if _table_exists(cur, "model_routes"):
            _mark_schema_ready("model_routes")
            return
        cur.execute("SELECT pg_advisory_xact_lock(hashtext('model_routes_schema'));")
        if _table_exists(cur, "model_routes"):
            _mark_schema_ready("model_routes")
            return
        cur.execute(
            """
            CREATE TABLE model_routes (
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
        _mark_schema_ready("model_routes")


def ensure_model_providers_table(cur):
    if _SCHEMA_FLAGS["model_providers"]:
        return
    if _table_exists(cur, "model_providers"):
        _mark_schema_ready("model_providers")
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_FLAGS["model_providers"]:
            return
        if _table_exists(cur, "model_providers"):
            _mark_schema_ready("model_providers")
            return
        cur.execute("SELECT pg_advisory_xact_lock(hashtext('model_providers_schema'));")
        if _table_exists(cur, "model_providers"):
            _mark_schema_ready("model_providers")
            return
        cur.execute(
            """
            CREATE TABLE model_providers (
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
        _mark_schema_ready("model_providers")


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
