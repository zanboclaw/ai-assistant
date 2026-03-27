from fastapi.testclient import TestClient

from apps.api.bootstrap.app_factory import create_app


def test_health_endpoints_are_available(monkeypatch):
    monkeypatch.setattr("apps.api.routes.health_routes._fetch_schema_version", lambda container: "0003_runtime_schema_finalize")
    app = create_app()
    client = TestClient(app)

    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json()["schema_version"] == "0003_runtime_schema_finalize"
    version_payload = client.get("/version").json()
    assert version_payload["schema_version"] == "0003_runtime_schema_finalize"
    assert "git_short_commit" in version_payload

