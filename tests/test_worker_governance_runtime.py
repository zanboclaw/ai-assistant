from governance_runtime import (
    ensure_tool_registry_table,
    get_model_provider_client,
    get_model_route_config,
    load_tool_registry_settings,
    reset_governance_runtime_cache,
)


class FakeCursor:
    def __init__(self, *, fetchone_results=None, fetchall_results=None):
        self.fetchone_results = list(fetchone_results or [])
        self.fetchall_results = list(fetchall_results or [])
        self.executed = []
        self.closed = False

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        if self.fetchone_results:
            return self.fetchone_results.pop(0)
        return None

    def fetchall(self):
        if self.fetchall_results:
            return self.fetchall_results.pop(0)
        return []

    def close(self):
        self.closed = True


class FakeConn:
    def __init__(self, cursor):
        self.cursor_instance = cursor
        self.commit_called = 0
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commit_called += 1

    def close(self):
        self.closed = True


class FakeOpenAI:
    def __init__(self, *, api_key, base_url):
        self.api_key = api_key
        self.base_url = base_url


def teardown_function():
    reset_governance_runtime_cache()


def test_ensure_tool_registry_table_defers_to_runtime_bootstrap_when_not_active():
    cursor = FakeCursor()
    calls = []

    ensure_tool_registry_table(
        cursor,
        runtime_schema_bootstrap_active=False,
        ensure_runtime_schema_bootstrapped=lambda: calls.append("bootstrapped"),
    )

    assert calls == ["bootstrapped"]
    assert cursor.executed == []


def test_ensure_tool_registry_table_skips_backfill_alters_after_runtime_schema_finalize():
    cursor = FakeCursor(
        fetchone_results=[
            {"regclass": "tool_registry_entries"},
            {"regclass": "schema_migrations"},
            {"migration_id": "0003_runtime_schema_finalize"},
        ]
    )

    ensure_tool_registry_table(
        cursor,
        runtime_schema_bootstrap_active=True,
        ensure_runtime_schema_bootstrapped=lambda: None,
    )

    sql = "\n".join(str(query) for query, _params in cursor.executed)
    assert "ALTER TABLE tool_registry_entries" not in sql


def test_load_tool_registry_settings_merges_defaults_and_db_rows():
    cursor = FakeCursor(
        fetchone_results=[{"regclass": "tool_registry_entries"}],
        fetchall_results=[
            [
                {
                    "tool_name": "web_search",
                    "enabled": True,
                    "provider_type": "builtin",
                    "transport": "local",
                    "server_name": "",
                    "provider_config": '{"depth":"basic"}',
                    "risk_level": "medium",
                    "approval_required": False,
                    "description": "search",
                }
            ]
        ],
    )
    conn = FakeConn(cursor)

    settings = load_tool_registry_settings(
        force_refresh=True,
        default_tool_registry={"file_read": {"enabled": True, "risk_level": "low"}},
        cache_ttl_seconds=30,
        get_conn=lambda: conn,
        seed_default_tool_registry_fn=lambda cur: None,
        parse_jsonish=lambda value, default: {"depth": "basic"} if value else default,
    )

    assert settings["file_read"]["enabled"] is True
    assert settings["web_search"]["provider_config"] == {"depth": "basic"}
    assert conn.commit_called == 1
    assert cursor.closed is True
    assert conn.closed is True


def test_get_model_provider_client_caches_openai_compatible_clients():
    created = []

    def fake_openai_cls(*, api_key, base_url):
        client = FakeOpenAI(api_key=api_key, base_url=base_url)
        created.append(client)
        return client

    provider_config = {
        "driver": "openai_compatible",
        "base_url": "https://example.test/v1",
        "api_key_env": "EXAMPLE_API_KEY",
        "enabled": True,
    }

    first = get_model_provider_client(
        "deepseek",
        get_model_provider_config_fn=lambda _name: provider_config,
        openai_cls=fake_openai_cls,
        env={"EXAMPLE_API_KEY": "secret-key"},
    )
    second = get_model_provider_client(
        "deepseek",
        get_model_provider_config_fn=lambda _name: provider_config,
        openai_cls=fake_openai_cls,
        env={"EXAMPLE_API_KEY": "secret-key"},
    )

    assert first is second
    assert len(created) == 1
    assert first.api_key == "secret-key"


def test_get_model_route_config_merges_route_overrides_and_validates_provider():
    route = get_model_route_config(
        "planner",
        route_overrides={"planner": {"model_name": "planner-override", "temperature": 0.6}},
        load_model_route_settings_fn=lambda: {
            "planner": {
                "provider": "deepseek",
                "model_name": "planner-default",
                "temperature": 0.2,
                "max_tokens": 800,
                "enabled": True,
            }
        },
        get_model_provider_config_fn=lambda provider_name: {"provider_name": provider_name},
    )

    assert route["model_name"] == "planner-override"
    assert route["temperature"] == 0.6
    assert route["provider"] == "deepseek"
