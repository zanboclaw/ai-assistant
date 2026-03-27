CREATE TABLE IF NOT EXISTS risk_policies (
    id SERIAL PRIMARY KEY,
    policy_key TEXT NOT NULL UNIQUE,
    value_type TEXT NOT NULL,
    policy_value TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE risk_policies
    ADD COLUMN IF NOT EXISTS value_type TEXT,
    ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

UPDATE risk_policies
SET value_type = COALESCE(NULLIF(value_type, ''), 'json')
WHERE value_type IS NULL OR value_type = '';

UPDATE risk_policies
SET description = COALESCE(description, '')
WHERE description IS NULL;

ALTER TABLE risk_policies
    ALTER COLUMN value_type SET NOT NULL,
    ALTER COLUMN policy_value TYPE TEXT USING policy_value::text,
    ALTER COLUMN policy_value SET NOT NULL,
    ALTER COLUMN description SET NOT NULL;

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

ALTER TABLE tool_registry_entries
    ADD COLUMN IF NOT EXISTS provider_type TEXT NOT NULL DEFAULT 'builtin',
    ADD COLUMN IF NOT EXISTS transport TEXT NOT NULL DEFAULT 'local',
    ADD COLUMN IF NOT EXISTS server_name TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS provider_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS approval_required BOOLEAN NOT NULL DEFAULT FALSE;

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

CREATE TABLE IF NOT EXISTS access_actors (
    actor_name TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    tenant_key TEXT NOT NULL DEFAULT 'default',
    permission_overrides TEXT NOT NULL DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE access_actors
    ADD COLUMN IF NOT EXISTS tenant_key TEXT NOT NULL DEFAULT 'default',
    ADD COLUMN IF NOT EXISTS permission_overrides TEXT NOT NULL DEFAULT '[]';

CREATE TABLE IF NOT EXISTS access_quotas (
    actor_name TEXT PRIMARY KEY REFERENCES access_actors(actor_name) ON DELETE CASCADE,
    daily_task_limit INTEGER NOT NULL,
    active_task_limit INTEGER NOT NULL,
    daily_token_limit INTEGER NOT NULL DEFAULT 0,
    max_parallel_agents INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE access_quotas
    ADD COLUMN IF NOT EXISTS daily_token_limit INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS max_parallel_agents INTEGER NOT NULL DEFAULT 0;
