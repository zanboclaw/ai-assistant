from __future__ import annotations

import json
import os
import time
from typing import Any

from core.schema_migration_runtime import is_runtime_schema_finalized

_risk_policy_cache_value: dict[str, Any] | None = None
_risk_policy_cache_expires_at = 0.0
_tool_registry_cache_value: dict[str, dict[str, Any]] | None = None
_tool_registry_cache_expires_at = 0.0
_model_route_cache_value: dict[str, dict[str, Any]] | None = None
_model_route_cache_expires_at = 0.0
_model_provider_cache_value: dict[str, dict[str, Any]] | None = None
_model_provider_cache_expires_at = 0.0
_model_provider_client_cache: dict[tuple[str, str, str], Any] = {}


def reset_governance_runtime_cache():
    global _risk_policy_cache_value, _risk_policy_cache_expires_at
    global _tool_registry_cache_value, _tool_registry_cache_expires_at
    global _model_route_cache_value, _model_route_cache_expires_at
    global _model_provider_cache_value, _model_provider_cache_expires_at

    _risk_policy_cache_value = None
    _risk_policy_cache_expires_at = 0.0
    _tool_registry_cache_value = None
    _tool_registry_cache_expires_at = 0.0
    _model_route_cache_value = None
    _model_route_cache_expires_at = 0.0
    _model_provider_cache_value = None
    _model_provider_cache_expires_at = 0.0
    _model_provider_client_cache.clear()


def ensure_risk_policies_table(cur):
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


def ensure_tool_registry_table(
    cur,
    *,
    runtime_schema_bootstrap_active: bool,
    ensure_runtime_schema_bootstrapped,
):
    if not runtime_schema_bootstrap_active:
        ensure_runtime_schema_bootstrapped()
        return
    cur.execute("SELECT pg_advisory_xact_lock(hashtext('tool_registry_entries_schema'));")
    cur.execute("SELECT to_regclass('public.tool_registry_entries') AS regclass;")
    if not cur.fetchone()["regclass"]:
        cur.execute(
            """
            CREATE TABLE tool_registry_entries (
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
    if not is_runtime_schema_finalized(cur):
        cur.execute("ALTER TABLE tool_registry_entries ADD COLUMN IF NOT EXISTS provider_type TEXT NOT NULL DEFAULT 'builtin';")
        cur.execute("ALTER TABLE tool_registry_entries ADD COLUMN IF NOT EXISTS transport TEXT NOT NULL DEFAULT 'local';")
        cur.execute("ALTER TABLE tool_registry_entries ADD COLUMN IF NOT EXISTS server_name TEXT NOT NULL DEFAULT '';")
        cur.execute("ALTER TABLE tool_registry_entries ADD COLUMN IF NOT EXISTS provider_config JSONB NOT NULL DEFAULT '{}'::jsonb;")
        cur.execute("ALTER TABLE tool_registry_entries ADD COLUMN IF NOT EXISTS approval_required BOOLEAN NOT NULL DEFAULT FALSE;")


def ensure_model_routes_table(
    cur,
    *,
    runtime_schema_bootstrap_active: bool,
    ensure_runtime_schema_bootstrapped,
):
    if not runtime_schema_bootstrap_active:
        ensure_runtime_schema_bootstrapped()
        return
    cur.execute("SELECT pg_advisory_xact_lock(hashtext('model_routes_schema'));")
    cur.execute("SELECT to_regclass('public.model_routes') AS regclass;")
    if cur.fetchone()["regclass"]:
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


def ensure_model_providers_table(
    cur,
    *,
    runtime_schema_bootstrap_active: bool,
    ensure_runtime_schema_bootstrapped,
):
    if not runtime_schema_bootstrap_active:
        ensure_runtime_schema_bootstrapped()
        return
    cur.execute("SELECT pg_advisory_xact_lock(hashtext('model_providers_schema'));")
    cur.execute("SELECT to_regclass('public.model_providers') AS regclass;")
    if cur.fetchone()["regclass"]:
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


def seed_default_tool_registry(
    cur,
    *,
    runtime_schema_bootstrap_active: bool,
    ensure_runtime_schema_bootstrapped,
    ensure_tool_registry_table_fn,
    default_tool_registry: dict[str, dict[str, Any]],
    safe_json_dumps,
):
    if not runtime_schema_bootstrap_active:
        ensure_runtime_schema_bootstrapped()
        return
    ensure_tool_registry_table_fn(cur)
    for tool_name, config in default_tool_registry.items():
        cur.execute(
            """
            INSERT INTO tool_registry_entries (
                tool_name, enabled, provider_type, transport, server_name, provider_config, risk_level, approval_required, description
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
            ON CONFLICT (tool_name) DO NOTHING;
            """,
            (
                tool_name,
                bool(config["enabled"]),
                str(config.get("provider_type") or "builtin"),
                str(config.get("transport") or "local"),
                str(config.get("server_name") or ""),
                safe_json_dumps(config.get("provider_config") or {}),
                str(config["risk_level"]),
                bool(config.get("approval_required", False)),
                str(config["description"]),
            ),
        )


def seed_default_model_routes(
    cur,
    *,
    runtime_schema_bootstrap_active: bool,
    ensure_runtime_schema_bootstrapped,
    ensure_model_routes_table_fn,
    default_model_routes: dict[str, dict[str, Any]],
):
    if not runtime_schema_bootstrap_active:
        ensure_runtime_schema_bootstrapped()
        return
    ensure_model_routes_table_fn(cur)
    for route_name, config in default_model_routes.items():
        cur.execute(
            """
            INSERT INTO model_routes (route_name, provider, model_name, temperature, max_tokens, enabled, description)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (route_name) DO NOTHING;
            """,
            (
                route_name,
                str(config["provider"]),
                str(config["model_name"]),
                float(config["temperature"]),
                int(config["max_tokens"]),
                bool(config["enabled"]),
                "",
            ),
        )


def seed_default_model_providers(
    cur,
    *,
    runtime_schema_bootstrap_active: bool,
    ensure_runtime_schema_bootstrapped,
    ensure_model_providers_table_fn,
    default_model_providers: dict[str, dict[str, Any]],
):
    if not runtime_schema_bootstrap_active:
        ensure_runtime_schema_bootstrapped()
        return
    ensure_model_providers_table_fn(cur)
    for provider_name, config in default_model_providers.items():
        cur.execute(
            """
            INSERT INTO model_providers (provider_name, driver, base_url, api_key_env, enabled, description)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (provider_name) DO NOTHING;
            """,
            (
                provider_name,
                str(config["driver"]),
                str(config["base_url"]),
                str(config["api_key_env"]),
                bool(config["enabled"]),
                "",
            ),
        )


def seed_default_risk_policies(
    cur,
    *,
    default_risk_policies: dict[str, Any],
    safe_json_dumps,
):
    ensure_risk_policies_table(cur)
    descriptions = {
        "approval_low_risk_write_extensions": "新建这些扩展名的文件时可直接写入，无需审批。",
        "approval_sensitive_write_extensions": "写入这些脚本/配置类扩展名时必须审批。",
        "approval_sensitive_write_basenames": "写入这些特定文件名时必须审批。",
        "approval_require_for_existing_file_overwrite": "覆盖已有文件时是否要求审批。",
        "approval_require_for_hidden_files": "写入隐藏文件时是否要求审批。",
        "approval_allowed_http_methods": "这些 HTTP 方法默认允许直通，其余方法要求审批。",
        "approval_http_get_requires_approval_suffixes": "GET 请求命中这些域名后缀时仍要求审批。",
    }
    for policy_key, policy_value in default_risk_policies.items():
        cur.execute(
            """
            INSERT INTO risk_policies (policy_key, value_type, policy_value, description)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (policy_key) DO NOTHING;
            """,
            (
                policy_key,
                "bool" if isinstance(policy_value, bool) else "json",
                safe_json_dumps(policy_value),
                descriptions.get(policy_key, ""),
            ),
        )


def load_risk_policy_settings(
    *,
    force_refresh: bool = False,
    default_risk_policies: dict[str, Any],
    cache_ttl_seconds: int,
    get_conn,
    seed_default_risk_policies_fn,
) -> dict[str, Any]:
    global _risk_policy_cache_value, _risk_policy_cache_expires_at

    now = time.time()
    if not force_refresh and _risk_policy_cache_value is not None and now < _risk_policy_cache_expires_at:
        return _risk_policy_cache_value

    settings = dict(default_risk_policies)
    conn = get_conn()
    cur = conn.cursor()
    try:
        seed_default_risk_policies_fn(cur)
        conn.commit()
        cur.execute(
            """
            SELECT policy_key, policy_value
            FROM risk_policies;
            """
        )
        for row in cur.fetchall():
            policy_key = str(row.get("policy_key") or "").strip()
            if not policy_key:
                continue
            try:
                settings[policy_key] = json.loads(row.get("policy_value") or "")
            except Exception:
                continue
    finally:
        cur.close()
        conn.close()

    _risk_policy_cache_value = settings
    _risk_policy_cache_expires_at = now + cache_ttl_seconds
    return settings


def load_tool_registry_settings(
    *,
    force_refresh: bool = False,
    default_tool_registry: dict[str, dict[str, Any]],
    cache_ttl_seconds: int,
    get_conn,
    seed_default_tool_registry_fn,
    parse_jsonish,
) -> dict[str, dict[str, Any]]:
    global _tool_registry_cache_value, _tool_registry_cache_expires_at

    now = time.time()
    if not force_refresh and _tool_registry_cache_value is not None and now < _tool_registry_cache_expires_at:
        return _tool_registry_cache_value

    settings = {name: dict(config) for name, config in default_tool_registry.items()}
    conn = get_conn()
    cur = conn.cursor()
    try:
        seed_default_tool_registry_fn(cur)
        conn.commit()
        cur.execute(
            """
            SELECT tool_name, enabled, provider_type, transport, server_name, provider_config, risk_level, approval_required, description
            FROM tool_registry_entries;
            """
        )
        for row in cur.fetchall():
            tool_name = str(row.get("tool_name") or "").strip()
            if not tool_name:
                continue
            settings[tool_name] = {
                "enabled": bool(row.get("enabled")),
                "provider_type": str(row.get("provider_type") or "builtin"),
                "transport": str(row.get("transport") or "local"),
                "server_name": str(row.get("server_name") or ""),
                "provider_config": parse_jsonish(row.get("provider_config"), {}) or {},
                "risk_level": str(row.get("risk_level") or "low"),
                "approval_required": bool(row.get("approval_required")),
                "description": str(row.get("description") or ""),
            }
    finally:
        cur.close()
        conn.close()

    _tool_registry_cache_value = settings
    _tool_registry_cache_expires_at = now + cache_ttl_seconds
    return settings


def load_model_route_settings(
    *,
    force_refresh: bool = False,
    default_model_routes: dict[str, dict[str, Any]],
    cache_ttl_seconds: int,
    get_conn,
    seed_default_model_routes_fn,
) -> dict[str, dict[str, Any]]:
    global _model_route_cache_value, _model_route_cache_expires_at

    now = time.time()
    if not force_refresh and _model_route_cache_value is not None and now < _model_route_cache_expires_at:
        return _model_route_cache_value

    settings = {name: dict(config) for name, config in default_model_routes.items()}
    conn = get_conn()
    cur = conn.cursor()
    try:
        seed_default_model_routes_fn(cur)
        conn.commit()
        cur.execute(
            """
            SELECT route_name, provider, model_name, temperature, max_tokens, enabled
            FROM model_routes;
            """
        )
        for row in cur.fetchall():
            route_name = str(row.get("route_name") or "").strip()
            if not route_name:
                continue
            settings[route_name] = {
                "provider": str(row.get("provider") or "openai_compatible"),
                "model_name": str(row.get("model_name") or ""),
                "temperature": float(row.get("temperature") or 0.2),
                "max_tokens": int(row.get("max_tokens") or 800),
                "enabled": bool(row.get("enabled")),
            }
    finally:
        cur.close()
        conn.close()

    _model_route_cache_value = settings
    _model_route_cache_expires_at = now + cache_ttl_seconds
    return settings


def load_model_provider_settings(
    *,
    force_refresh: bool = False,
    default_model_providers: dict[str, dict[str, Any]],
    cache_ttl_seconds: int,
    get_conn,
    seed_default_model_providers_fn,
) -> dict[str, dict[str, Any]]:
    global _model_provider_cache_value, _model_provider_cache_expires_at

    now = time.time()
    if not force_refresh and _model_provider_cache_value is not None and now < _model_provider_cache_expires_at:
        return _model_provider_cache_value

    settings = {name: dict(config) for name, config in default_model_providers.items()}
    conn = get_conn()
    cur = conn.cursor()
    try:
        seed_default_model_providers_fn(cur)
        conn.commit()
        cur.execute(
            """
            SELECT provider_name, driver, base_url, api_key_env, enabled
            FROM model_providers;
            """
        )
        for row in cur.fetchall():
            provider_name = str(row.get("provider_name") or "").strip()
            if not provider_name:
                continue
            settings[provider_name] = {
                "driver": str(row.get("driver") or "openai_compatible"),
                "base_url": str(row.get("base_url") or "").strip(),
                "api_key_env": str(row.get("api_key_env") or "").strip(),
                "enabled": bool(row.get("enabled")),
            }
    finally:
        cur.close()
        conn.close()

    _model_provider_cache_value = settings
    _model_provider_cache_expires_at = now + cache_ttl_seconds
    return settings


def get_model_provider_config(
    provider_name: str,
    *,
    load_model_provider_settings_fn,
) -> dict[str, Any]:
    providers = load_model_provider_settings_fn()
    config = providers.get(provider_name)
    if config is None:
        raise ValueError(f"模型 provider 未注册: {provider_name}")
    if not bool(config.get("enabled", True)):
        raise ValueError(f"模型 provider 已禁用: {provider_name}")
    return config


def get_model_provider_client(
    provider_name: str,
    *,
    get_model_provider_config_fn,
    openai_cls,
    env: dict[str, str] | None = None,
):
    config = get_model_provider_config_fn(provider_name)
    driver = str(config.get("driver") or "openai_compatible")
    if driver != "openai_compatible":
        raise ValueError(f"不支持的模型 provider driver: {driver}")

    base_url = str(config.get("base_url") or "").strip()
    api_key_env = str(config.get("api_key_env") or "").strip()
    if not base_url:
        raise ValueError(f"模型 provider 缺少 base_url: {provider_name}")
    if not api_key_env:
        raise ValueError(f"模型 provider 缺少 api_key_env: {provider_name}")

    api_key = (env or os.environ).get(api_key_env, "")
    cache_key = (provider_name, base_url, api_key_env)
    client = _model_provider_client_cache.get(cache_key)
    if client is None:
        client = openai_cls(api_key=api_key, base_url=base_url)
        _model_provider_client_cache[cache_key] = client
    return client


def get_model_route_config(
    route_name: str,
    *,
    load_model_route_settings_fn,
    get_model_provider_config_fn,
    route_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    routes = load_model_route_settings_fn()
    config = routes.get(route_name)
    if config is None:
        raise ValueError(f"模型路由未注册: {route_name}")
    merged_config = dict(config)
    override_config = (route_overrides or {}).get(route_name)
    if isinstance(override_config, dict):
        merged_config.update(override_config)
    merged_config = {
        "provider": str(merged_config.get("provider") or "openai_compatible"),
        "model_name": str(merged_config.get("model_name") or ""),
        "temperature": float(merged_config.get("temperature") or 0.2),
        "max_tokens": int(merged_config.get("max_tokens") or 800),
        "enabled": bool(merged_config.get("enabled", True)),
    }
    if not bool(merged_config.get("enabled", True)):
        raise ValueError(f"模型路由已禁用: {route_name}")
    provider_name = str(merged_config.get("provider") or "").strip()
    if not provider_name:
        raise ValueError(f"模型路由缺少 provider: {route_name}")
    get_model_provider_config_fn(provider_name)
    return merged_config


def snapshot_model_route_config(
    route_name: str,
    *,
    get_model_route_config_fn,
    route_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    route = get_model_route_config_fn(route_name, route_overrides=route_overrides)
    return {
        "route_name": route_name,
        "provider": str(route.get("provider") or ""),
        "model_name": str(route.get("model_name") or ""),
        "temperature": float(route.get("temperature") or 0.0),
        "max_tokens": int(route.get("max_tokens") or 0),
        "enabled": bool(route.get("enabled", True)),
    }


def serialize_model_route_runtime_info(route_name: str, route: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(route, dict):
        return {}
    return {
        "route_name": str(route_name or "").strip(),
        "provider": str(route.get("provider") or "").strip(),
        "model_name": str(route.get("model_name") or "").strip(),
        "temperature": float(route.get("temperature") or 0.0),
        "max_tokens": int(route.get("max_tokens") or 0),
        "enabled": bool(route.get("enabled", True)),
    }


def ensure_tool_enabled(
    tool_name: str,
    *,
    load_tool_registry_settings_fn,
):
    registry = load_tool_registry_settings_fn()
    config = registry.get(tool_name)
    if config is None:
        raise ValueError(f"工具未注册: {tool_name}")
    if not bool(config.get("enabled", True)):
        raise ValueError(f"工具已禁用: {tool_name}")


def get_tool_registry_entry(
    tool_name: str,
    *,
    load_tool_registry_settings_fn,
) -> dict[str, Any] | None:
    registry = load_tool_registry_settings_fn()
    config = registry.get(tool_name)
    return dict(config) if isinstance(config, dict) else None
