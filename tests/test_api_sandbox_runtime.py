from __future__ import annotations

import re
import sys
from pathlib import Path

from fastapi import HTTPException

API_ROOT = Path(__file__).resolve().parents[1] / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from api_sandbox_runtime import (
    apply_unified_patch_to_text,
    build_shadow_validation_runtime_overrides,
    get_redis_monitor_stats,
    normalize_sandbox_file_acceptance_payload_with_context,
    normalize_sandbox_file_payload,
    resolve_sandbox_change_path,
    resolve_workspace_acceptance_script_path,
    resolve_workspace_source_path,
)


def test_build_shadow_validation_runtime_overrides_copies_model_route_overlay():
    payload = build_shadow_validation_runtime_overrides(
        proposal_id=7,
        validation_mode="task_replay_compare",
        make_json_compatible_fn=lambda value: value,
        candidate_overlay={
            "target_type": "model_route",
            "target_key": "planner",
            "proposed_payload": {"provider": "deepseek"},
        },
        source_change_request_id=21,
    )

    assert payload["shadow_validation"]["proposal_id"] == 7
    assert payload["shadow_validation"]["source_change_request_id"] == 21
    assert payload["model_route_overrides"]["planner"]["provider"] == "deepseek"


def test_resolve_sandbox_and_workspace_paths_enforce_boundaries(tmp_path):
    sandbox_root = tmp_path / "sandbox"
    workspace_root = tmp_path / "workspace"
    scripts_root = workspace_root / "scripts"
    sandbox_root.mkdir()
    scripts_root.mkdir(parents=True)
    source_file = workspace_root / "README.md"
    source_file.write_text("hello", encoding="utf-8")
    script_file = scripts_root / "check.sh"
    script_file.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")

    sandbox_path = resolve_sandbox_change_path(
        "docs/test.txt",
        sandbox_change_root=sandbox_root,
        http_exception_cls=HTTPException,
    )
    workspace_path = resolve_workspace_source_path(
        "README.md",
        workspace_root=workspace_root,
        sandbox_change_root=sandbox_root,
        http_exception_cls=HTTPException,
    )
    acceptance_path = resolve_workspace_acceptance_script_path(
        "scripts/check.sh",
        workspace_root=workspace_root,
        scripts_root=scripts_root,
        http_exception_cls=HTTPException,
    )

    assert sandbox_path == sandbox_root / "docs" / "test.txt"
    assert workspace_path == source_file.resolve()
    assert acceptance_path == script_file.resolve()

    try:
        resolve_sandbox_change_path("../oops", sandbox_change_root=sandbox_root, http_exception_cls=HTTPException)
    except HTTPException as exc:
        assert exc.status_code == 400
    else:  # pragma: no cover
        raise AssertionError("expected sandbox path validation failure")


def test_apply_unified_patch_to_text_returns_patch_stats():
    patched, stats = apply_unified_patch_to_text(
        "hello\nworld\n",
        "@@ -1,2 +1,2 @@\n hello\n-world\n+codex\n",
        unified_hunk_re=re.compile(
            r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
        ),
        http_exception_cls=HTTPException,
    )

    assert patched == "hello\ncodex\n"
    assert stats["hunk_count"] == 1
    assert stats["added_line_count"] == 1
    assert stats["removed_line_count"] == 1


def test_normalize_sandbox_file_payload_supports_source_patch_and_acceptance(tmp_path):
    workspace_root = tmp_path / "workspace"
    sandbox_root = tmp_path / "sandbox"
    scripts_root = workspace_root / "scripts"
    workspace_root.mkdir()
    sandbox_root.mkdir()
    scripts_root.mkdir()
    source_file = workspace_root / "source.txt"
    source_file.write_text("line1\nline2\n", encoding="utf-8")
    script_file = scripts_root / "check.sh"
    script_file.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")

    normalized = normalize_sandbox_file_payload(
        {
            "source_path": "source.txt",
            "patch": "@@ -1,2 +1,2 @@\n line1\n-line2\n+line2 updated\n",
            "acceptance": {"script_path": "scripts/check.sh", "timeout_seconds": 5},
        },
        file_encoding="utf-8",
        content_limit_bytes=4096,
        normalize_sandbox_file_acceptance_payload_fn=lambda payload: {
            "script_path": resolve_workspace_acceptance_script_path(
                payload["script_path"],
                workspace_root=workspace_root,
                scripts_root=scripts_root,
                http_exception_cls=HTTPException,
            ).relative_to(workspace_root).as_posix(),
            "timeout_seconds": 5,
            "env": {},
        },
        read_workspace_source_file_snapshot_fn=lambda source_path: (
            source_file.read_text(encoding="utf-8"),
            {"source_path": source_path, "source_hash": "abc"},
        ),
        apply_unified_patch_to_text_fn=lambda source_content, patch_text: (
            source_content.replace("line2\n", "line2 updated\n"),
            {"line_count": len(patch_text.splitlines()), "hunk_count": 1, "added_line_count": 1, "removed_line_count": 1},
        ),
        http_exception_cls=HTTPException,
    )

    assert normalized["exists"] is True
    assert normalized["content"].endswith("line2 updated\n")
    assert normalized["patch_applied"]["hunk_count"] == 1
    assert normalized["acceptance"]["script_path"] == "scripts/check.sh"


def test_get_redis_monitor_stats_counts_queue_and_claims():
    class FakeRedis:
        def llen(self, _name):
            return 3

        def scan_iter(self, match=None, count=None):
            assert match == "task_claim:*"
            assert count == 100
            return iter(["task_claim:1", "task_claim:2"])

    stats = get_redis_monitor_stats(get_redis_client_fn=lambda: FakeRedis())

    assert stats == {"queue_depth": 3, "active_claims": 2}


def test_normalize_sandbox_file_acceptance_payload_with_context_serializes_script_path(tmp_path):
    script_path = tmp_path / "scripts" / "check.sh"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")

    normalized = normalize_sandbox_file_acceptance_payload_with_context(
        {"script_path": "scripts/check.sh"},
        normalize_sandbox_file_acceptance_payload_fn=lambda _payload: {
            "script_path": script_path,
            "timeout_seconds": 5,
            "env": {},
        },
        workspace_root=tmp_path,
    )

    assert normalized["script_path"] == "scripts/check.sh"
