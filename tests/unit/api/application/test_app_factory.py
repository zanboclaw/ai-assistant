from fastapi.testclient import TestClient

from apps.api.bootstrap.app_factory import create_app


def test_app_factory_exposes_root_and_version_without_database():
    app = create_app()
    client = TestClient(app)

    assert client.get("/").json() == {"message": "ai assistant api is running"}
    version_payload = client.get("/version").json()
    assert version_payload["schema_version"] == "unknown"
    assert "git_short_commit" in version_payload

