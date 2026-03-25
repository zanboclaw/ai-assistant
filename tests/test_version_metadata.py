from __future__ import annotations

from core import version_metadata


def test_get_runtime_version_metadata_prefers_env_overrides(monkeypatch):
    monkeypatch.setenv("APP_GIT_COMMIT", "abc123456789")
    monkeypatch.setenv("APP_GIT_BRANCH", "release/test")
    monkeypatch.setenv("APP_GIT_DIRTY", "")
    monkeypatch.setenv("APP_BUILD_TIMESTAMP", "2026-03-25T00:00:00+00:00")
    monkeypatch.setattr(version_metadata, "load_version_file", lambda: {"current_version": "stage7-foundation", "repository": "ai-assistant"})
    monkeypatch.setattr(version_metadata, "_run_git_command", lambda _args: "")

    payload = version_metadata.get_runtime_version_metadata()

    assert payload["current_version"] == "stage7-foundation"
    assert payload["git_commit"] == "abc123456789"
    assert payload["git_short_commit"] == "abc123456789"[:12]
    assert payload["git_branch"] == "release/test"
    assert payload["build_timestamp"] == "2026-03-25T00:00:00+00:00"
