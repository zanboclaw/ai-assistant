from __future__ import annotations

import hashlib
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_shadow_validation_runtime_overrides(
    *,
    proposal_id: int,
    validation_mode: str,
    make_json_compatible_fn,
    candidate_overlay: dict[str, Any] | None = None,
    source_change_request_id: int | None = None,
) -> dict[str, Any]:
    overlay = candidate_overlay or {}
    runtime_overrides: dict[str, Any] = {
        "shadow_validation": {
            "proposal_id": int(proposal_id),
            "validation_mode": validation_mode,
        }
    }
    if source_change_request_id is not None:
        runtime_overrides["shadow_validation"]["source_change_request_id"] = int(source_change_request_id)
    if overlay:
        runtime_overrides["shadow_validation"]["candidate_overlay"] = make_json_compatible_fn(overlay)
    if (
        str(overlay.get("target_type") or "").strip() == "model_route"
        and str(overlay.get("target_key") or "").strip()
        and isinstance(overlay.get("proposed_payload"), dict)
    ):
        runtime_overrides["model_route_overrides"] = {
            str(overlay["target_key"]).strip(): make_json_compatible_fn(overlay.get("proposed_payload") or {})
        }
    return runtime_overrides


def resolve_sandbox_change_path(
    target_key: str,
    *,
    sandbox_change_root: Path,
    http_exception_cls,
) -> Path:
    raw_target_key = str(target_key or "").strip()
    if not raw_target_key:
        raise http_exception_cls(status_code=400, detail="sandbox_file target_key is required")
    if raw_target_key.startswith(("/", "\\")):
        raise http_exception_cls(status_code=400, detail="sandbox_file target_key must be a relative path")
    candidate = (sandbox_change_root / raw_target_key).resolve()
    try:
        candidate.relative_to(sandbox_change_root)
    except ValueError as exc:
        raise http_exception_cls(status_code=400, detail="sandbox_file target_key must stay within sandbox root") from exc
    if candidate == sandbox_change_root:
        raise http_exception_cls(status_code=400, detail="sandbox_file target_key must point to a file")
    return candidate


def resolve_workspace_source_path(
    source_path: str,
    *,
    workspace_root: Path,
    sandbox_change_root: Path,
    http_exception_cls,
) -> Path:
    raw_source_path = str(source_path or "").strip()
    if not raw_source_path:
        raise http_exception_cls(status_code=400, detail="sandbox_file source_path must be a non-empty string")
    candidate = Path(raw_source_path)
    resolved = candidate.resolve() if candidate.is_absolute() else (workspace_root / candidate).resolve()
    try:
        resolved.relative_to(workspace_root)
    except ValueError as exc:
        raise http_exception_cls(status_code=400, detail="sandbox_file source_path must stay within workspace root") from exc
    try:
        resolved.relative_to(sandbox_change_root)
    except ValueError:
        pass
    else:
        raise http_exception_cls(status_code=400, detail="sandbox_file source_path must point outside sandbox root")
    if resolved == workspace_root:
        raise http_exception_cls(status_code=400, detail="sandbox_file source_path must point to a file")
    if not resolved.exists():
        raise http_exception_cls(status_code=404, detail=f"sandbox_file source_path not found: {raw_source_path}")
    if resolved.is_dir():
        raise http_exception_cls(
            status_code=400,
            detail=f"sandbox_file source_path points to a directory: {raw_source_path}",
        )
    return resolved


def read_workspace_source_file_snapshot(
    source_path: str,
    *,
    resolve_workspace_source_path_fn,
    workspace_root: Path,
    file_encoding: str,
    content_limit_bytes: int,
    http_exception_cls,
) -> tuple[str, dict[str, Any]]:
    path = resolve_workspace_source_path_fn(source_path)
    size_bytes = path.stat().st_size
    if size_bytes > content_limit_bytes:
        raise http_exception_cls(
            status_code=400,
            detail=f"sandbox_file source_path exceeds {content_limit_bytes} bytes: {source_path}",
        )
    try:
        content = path.read_text(encoding=file_encoding)
    except UnicodeDecodeError as exc:
        raise http_exception_cls(
            status_code=400,
            detail=f"sandbox_file source_path is not valid {file_encoding}: {source_path}",
        ) from exc
    encoded_content = content.encode(file_encoding)
    return content, {
        "source_kind": "workspace_file",
        "source_path": path.relative_to(workspace_root).as_posix(),
        "source_hash": hashlib.sha256(encoded_content).hexdigest(),
        "source_size_bytes": len(encoded_content),
    }


def resolve_workspace_acceptance_script_path(
    script_path: str,
    *,
    workspace_root: Path,
    scripts_root: Path,
    http_exception_cls,
) -> Path:
    raw_script_path = str(script_path or "").strip()
    if not raw_script_path:
        raise http_exception_cls(
            status_code=400,
            detail="sandbox_file acceptance script_path must be a non-empty string",
        )
    candidate = Path(raw_script_path)
    resolved = candidate.resolve() if candidate.is_absolute() else (workspace_root / candidate).resolve()
    try:
        resolved.relative_to(workspace_root)
    except ValueError as exc:
        raise http_exception_cls(
            status_code=400,
            detail="sandbox_file acceptance script_path must stay within workspace root",
        ) from exc
    try:
        resolved.relative_to(scripts_root)
    except ValueError as exc:
        raise http_exception_cls(
            status_code=400,
            detail="sandbox_file acceptance script_path must stay within workspace scripts/",
        ) from exc
    if resolved == workspace_root or resolved == scripts_root:
        raise http_exception_cls(
            status_code=400,
            detail="sandbox_file acceptance script_path must point to a file",
        )
    if not resolved.exists():
        raise http_exception_cls(
            status_code=404,
            detail=f"sandbox_file acceptance script_path not found: {raw_script_path}",
        )
    if resolved.is_dir():
        raise http_exception_cls(
            status_code=400,
            detail=f"sandbox_file acceptance script_path points to a directory: {raw_script_path}",
        )
    return resolved


def normalize_sandbox_file_acceptance_payload(
    acceptance_payload: Any,
    *,
    resolve_workspace_acceptance_script_path_fn,
    file_encoding: str,
    default_timeout_seconds: int,
    max_timeout_seconds: int,
    max_env_vars: int,
    max_env_bytes: int,
    env_key_re,
    http_exception_cls,
) -> dict[str, Any]:
    if acceptance_payload is None:
        return {}
    if not isinstance(acceptance_payload, dict):
        raise http_exception_cls(status_code=400, detail="sandbox_file acceptance must be a JSON object")
    script_path_value = acceptance_payload.get("script_path")
    if not isinstance(script_path_value, str) or not script_path_value.strip():
        raise http_exception_cls(
            status_code=400,
            detail="sandbox_file acceptance script_path must be a non-empty string",
        )
    timeout_raw = acceptance_payload.get("timeout_seconds", default_timeout_seconds)
    try:
        timeout_seconds = int(timeout_raw)
    except (TypeError, ValueError) as exc:
        raise http_exception_cls(
            status_code=400,
            detail="sandbox_file acceptance timeout_seconds must be an integer",
        ) from exc
    if timeout_seconds <= 0 or timeout_seconds > max_timeout_seconds:
        raise http_exception_cls(
            status_code=400,
            detail=f"sandbox_file acceptance timeout_seconds must be between 1 and {max_timeout_seconds}",
        )
    env_payload = acceptance_payload.get("env") or {}
    if not isinstance(env_payload, dict):
        raise http_exception_cls(
            status_code=400,
            detail="sandbox_file acceptance env must be a JSON object when provided",
        )
    if len(env_payload) > max_env_vars:
        raise http_exception_cls(
            status_code=400,
            detail=f"sandbox_file acceptance env exceeds {max_env_vars} entries",
        )
    normalized_env: dict[str, str] = {}
    env_bytes = 0
    for raw_key in sorted(env_payload.keys()):
        key = str(raw_key or "").strip()
        if not env_key_re.fullmatch(key):
            raise http_exception_cls(
                status_code=400,
                detail=f"sandbox_file acceptance env key is invalid: {raw_key}",
            )
        raw_value = env_payload.get(raw_key)
        if raw_value is None:
            value = ""
        elif isinstance(raw_value, (str, int, float, bool)):
            value = str(raw_value)
        else:
            raise http_exception_cls(
                status_code=400,
                detail=f"sandbox_file acceptance env value must be scalar: {key}",
            )
        env_bytes += len(key.encode("utf-8")) + len(value.encode("utf-8"))
        if env_bytes > max_env_bytes:
            raise http_exception_cls(
                status_code=400,
                detail=f"sandbox_file acceptance env exceeds {max_env_bytes} bytes",
            )
        normalized_env[key] = value
    script_path = resolve_workspace_acceptance_script_path_fn(script_path_value)
    script_bytes = script_path.read_bytes()
    return {
        "script_path": script_path,
        "script_path_label": script_path_value.strip(),
        "timeout_seconds": timeout_seconds,
        "env": normalized_env,
        "script_hash": hashlib.sha256(script_bytes).hexdigest(),
        "script_size_bytes": len(script_bytes),
        "encoding": file_encoding,
    }


def normalize_sandbox_file_acceptance_payload_with_context(
    acceptance_payload: Any,
    *,
    normalize_sandbox_file_acceptance_payload_fn,
    workspace_root: Path,
) -> dict[str, Any]:
    normalized = normalize_sandbox_file_acceptance_payload_fn(acceptance_payload)
    if normalized and isinstance(normalized.get("script_path"), Path):
        return {
            **normalized,
            "script_path": normalized["script_path"].relative_to(workspace_root).as_posix(),
        }
    return normalized


def clip_sandbox_file_acceptance_output(value: str | bytes | None, *, output_limit: int) -> str:
    if value is None:
        return ""
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
    if len(text) <= output_limit:
        return text
    return text[:output_limit] + "\n...[truncated]"


def execute_sandbox_file_acceptance(
    *,
    change_request_id: int,
    target_key: str,
    normalized_payload: dict[str, Any],
    resolve_workspace_acceptance_script_path_fn,
    resolve_sandbox_change_path_fn,
    clip_sandbox_file_acceptance_output_fn,
    workspace_root: Path,
    sandbox_change_root: Path,
    default_timeout_seconds: int,
    logger,
) -> tuple[str, dict[str, Any], datetime]:
    acceptance = normalized_payload.get("acceptance") or {}
    if not isinstance(acceptance, dict) or not acceptance:
        finished_at = datetime.now(timezone.utc)
        return "not_configured", {}, finished_at

    script_path = resolve_workspace_acceptance_script_path_fn(acceptance.get("script_path") or "")
    timeout_seconds = int(acceptance.get("timeout_seconds") or default_timeout_seconds)
    started_at = datetime.now(timezone.utc)
    start = time.perf_counter()
    sandbox_path = resolve_sandbox_change_path_fn(target_key)
    environment = os.environ.copy()
    environment.update(
        {
            "STAGE7_CHANGE_REQUEST_ID": str(change_request_id),
            "STAGE7_TARGET_TYPE": "sandbox_file",
            "STAGE7_SANDBOX_TARGET_KEY": target_key,
            "STAGE7_SANDBOX_ROOT": str(sandbox_change_root),
            "STAGE7_SANDBOX_FILE": str(sandbox_path),
            "STAGE7_WORKSPACE_ROOT": str(workspace_root),
        }
    )
    source_copy = normalized_payload.get("source_copy") or {}
    if isinstance(source_copy.get("source_path"), str) and source_copy.get("source_path"):
        environment["STAGE7_SOURCE_PATH"] = str(source_copy.get("source_path"))
    environment.update({str(key): str(value) for key, value in (acceptance.get("env") or {}).items()})

    report: dict[str, Any] = {
        "script_path": script_path.relative_to(workspace_root).as_posix(),
        "timeout_seconds": timeout_seconds,
        "env_keys": sorted((acceptance.get("env") or {}).keys()),
        "started_at": started_at.isoformat(),
    }
    try:
        completed = subprocess.run(
            ["/bin/bash", str(script_path)],
            cwd=str(workspace_root),
            env=environment,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        finished_at = datetime.now(timezone.utc)
        duration_ms = int(max(time.perf_counter() - start, 0.0) * 1000)
        status = "passed" if completed.returncode == 0 else "failed"
        report.update(
            {
                "status": status,
                "passed": completed.returncode == 0,
                "exit_code": int(completed.returncode),
                "duration_ms": duration_ms,
                "stdout": clip_sandbox_file_acceptance_output_fn(completed.stdout),
                "stderr": clip_sandbox_file_acceptance_output_fn(completed.stderr),
                "timed_out": False,
            }
        )
        return status, report, finished_at
    except subprocess.TimeoutExpired as exc:
        finished_at = datetime.now(timezone.utc)
        duration_ms = int(max(time.perf_counter() - start, 0.0) * 1000)
        report.update(
            {
                "status": "timed_out",
                "passed": False,
                "exit_code": None,
                "duration_ms": duration_ms,
                "stdout": clip_sandbox_file_acceptance_output_fn(exc.stdout),
                "stderr": clip_sandbox_file_acceptance_output_fn(exc.stderr),
                "timed_out": True,
            }
        )
        return "timed_out", report, finished_at
    except Exception as exc:
        finished_at = datetime.now(timezone.utc)
        duration_ms = int(max(time.perf_counter() - start, 0.0) * 1000)
        logger.exception("sandbox_file acceptance execution failed change_request_id=%s", change_request_id)
        report.update(
            {
                "status": "error",
                "passed": False,
                "exit_code": None,
                "duration_ms": duration_ms,
                "stdout": "",
                "stderr": clip_sandbox_file_acceptance_output_fn(str(exc)),
                "timed_out": False,
                "error_type": type(exc).__name__,
            }
        )
        return "error", report, finished_at


def apply_unified_patch_to_text(
    source_content: str,
    patch_text: str,
    *,
    unified_hunk_re,
    http_exception_cls,
) -> tuple[str, dict[str, Any]]:
    patch_value = str(patch_text or "")
    if not patch_value.strip():
        raise http_exception_cls(
            status_code=400,
            detail="sandbox_file patch must be a non-empty string when provided",
        )

    source_lines = source_content.splitlines(keepends=True)
    patch_lines = patch_value.splitlines(keepends=True)
    output_lines: list[str] = []
    source_index = 0
    line_index = 0
    hunk_count = 0
    added_line_count = 0
    removed_line_count = 0
    allowed_header_prefixes = ("diff --git ", "index ", "--- ", "+++ ")

    while line_index < len(patch_lines):
        header_line = patch_lines[line_index]
        if header_line.startswith("@@"):
            break
        if header_line.startswith(allowed_header_prefixes) or not header_line.strip():
            line_index += 1
            continue
        raise http_exception_cls(
            status_code=400,
            detail="sandbox_file patch must be a unified diff with at least one hunk",
        )

    while line_index < len(patch_lines):
        raw_header = patch_lines[line_index].rstrip("\n")
        match = unified_hunk_re.match(raw_header)
        if not match:
            raise http_exception_cls(
                status_code=400,
                detail=f"sandbox_file patch has invalid hunk header: {raw_header}",
            )

        old_start = int(match.group("old_start"))
        old_count = int(match.group("old_count") or "1")
        new_count = int(match.group("new_count") or "1")
        hunk_source_index = old_start if old_count == 0 else max(old_start - 1, 0)
        if hunk_source_index < source_index or hunk_source_index > len(source_lines):
            raise http_exception_cls(
                status_code=400,
                detail=f"sandbox_file patch hunk points outside source content: {raw_header}",
            )

        output_lines.extend(source_lines[source_index:hunk_source_index])
        source_index = hunk_source_index
        line_index += 1
        hunk_count += 1
        consumed_old = 0
        consumed_new = 0

        while line_index < len(patch_lines):
            patch_line = patch_lines[line_index]
            if patch_line.startswith("@@"):
                break
            if patch_line.startswith("\\"):
                line_index += 1
                continue
            if not patch_line:
                raise http_exception_cls(status_code=400, detail="sandbox_file patch contains an empty diff line")

            prefix = patch_line[0]
            diff_content = patch_line[1:]
            source_line = source_lines[source_index] if source_index < len(source_lines) else None

            if prefix == " ":
                if source_line != diff_content:
                    raise http_exception_cls(
                        status_code=400,
                        detail=f"sandbox_file patch context mismatch near source line {source_index + 1}",
                    )
                output_lines.append(source_line)
                source_index += 1
                consumed_old += 1
                consumed_new += 1
            elif prefix == "-":
                if source_line != diff_content:
                    raise http_exception_cls(
                        status_code=400,
                        detail=f"sandbox_file patch removal mismatch near source line {source_index + 1}",
                    )
                source_index += 1
                consumed_old += 1
                removed_line_count += 1
            elif prefix == "+":
                output_lines.append(diff_content)
                consumed_new += 1
                added_line_count += 1
            else:
                raise http_exception_cls(
                    status_code=400,
                    detail=f"sandbox_file patch has invalid diff line prefix: {prefix!r}",
                )
            line_index += 1

        if consumed_old != old_count or consumed_new != new_count:
            raise http_exception_cls(
                status_code=400,
                detail=(
                    "sandbox_file patch hunk length mismatch: "
                    f"expected -{old_count}/+{new_count}, got -{consumed_old}/+{consumed_new}"
                ),
            )

    if hunk_count == 0:
        raise http_exception_cls(status_code=400, detail="sandbox_file patch must include at least one hunk")

    output_lines.extend(source_lines[source_index:])
    patched_content = "".join(output_lines)
    return patched_content, {
        "format": "unified_diff",
        "hunk_count": hunk_count,
        "added_line_count": added_line_count,
        "removed_line_count": removed_line_count,
        "line_count": len(patch_value.splitlines()),
    }


def normalize_sandbox_file_payload(
    payload: dict[str, Any] | None,
    *,
    file_encoding: str,
    content_limit_bytes: int,
    normalize_sandbox_file_acceptance_payload_fn,
    read_workspace_source_file_snapshot_fn,
    apply_unified_patch_to_text_fn,
    http_exception_cls,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise http_exception_cls(status_code=400, detail="sandbox_file proposed_payload must be a JSON object")
    encoding = str(payload.get("encoding") or file_encoding).strip().lower() or file_encoding
    if encoding != file_encoding:
        raise http_exception_cls(status_code=400, detail=f"sandbox_file only supports {file_encoding} encoding")
    acceptance = normalize_sandbox_file_acceptance_payload_fn(payload.get("acceptance"))
    exists_value = payload.get("exists")
    if exists_value is None:
        exists = True
    elif isinstance(exists_value, bool):
        exists = exists_value
    else:
        raise http_exception_cls(status_code=400, detail="sandbox_file exists must be a boolean when provided")
    source_content = ""
    source_copy: dict[str, Any] = {}
    if "source_path" in payload:
        if not exists:
            raise http_exception_cls(status_code=400, detail="sandbox_file source_path cannot be used when exists=false")
        source_path_value = payload.get("source_path")
        if not isinstance(source_path_value, str) or not source_path_value.strip():
            raise http_exception_cls(
                status_code=400,
                detail="sandbox_file source_path must be a non-empty string when provided",
            )
        source_content, source_copy = read_workspace_source_file_snapshot_fn(source_path_value)
    content_value = payload.get("content")
    patch_input: dict[str, Any] = {}
    patch_applied: dict[str, Any] = {}
    patch_value = payload.get("patch")
    if patch_value is not None:
        if not exists:
            raise http_exception_cls(status_code=400, detail="sandbox_file patch cannot be used when exists=false")
        if isinstance(content_value, str):
            raise http_exception_cls(
                status_code=400,
                detail="sandbox_file content and patch cannot be provided together",
            )
        if not source_copy:
            raise http_exception_cls(status_code=400, detail="sandbox_file patch requires source_path")
        if not isinstance(patch_value, str) or not patch_value.strip():
            raise http_exception_cls(
                status_code=400,
                detail="sandbox_file patch must be a non-empty string when provided",
            )
        content, patch_stats = apply_unified_patch_to_text_fn(source_content, patch_value)
        patch_bytes = patch_value.encode(file_encoding)
        patch_input = {
            "format": "unified_diff",
            "input_hash": hashlib.sha256(patch_bytes).hexdigest(),
            "input_size_bytes": len(patch_bytes),
            "line_count": patch_stats["line_count"],
        }
        patch_applied = {
            "format": "unified_diff",
            "base_kind": "source_copy",
            "base_source_path": source_copy.get("source_path"),
            "base_source_hash": source_copy.get("source_hash"),
            "hunk_count": patch_stats["hunk_count"],
            "added_line_count": patch_stats["added_line_count"],
            "removed_line_count": patch_stats["removed_line_count"],
            "content_changed": content != source_content,
        }
    if exists:
        if patch_value is not None:
            pass
        elif isinstance(content_value, str):
            content = content_value
        elif source_copy:
            content = source_content
        else:
            raise http_exception_cls(status_code=400, detail="sandbox_file content is required when exists=true")
    else:
        content = ""
    if len(content.encode(file_encoding)) > content_limit_bytes:
        raise http_exception_cls(
            status_code=400,
            detail=f"sandbox_file content exceeds {content_limit_bytes} bytes",
        )
    normalized_payload = {
        "exists": exists,
        "content": content,
        "encoding": file_encoding,
    }
    if source_copy:
        normalized_payload["source_copy"] = {
            **source_copy,
            "content_matches_source": content == source_content,
        }
    if patch_input:
        normalized_payload["patch_input"] = patch_input
    if patch_applied:
        normalized_payload["patch_applied"] = patch_applied
    if acceptance:
        normalized_payload["acceptance"] = acceptance
    return normalized_payload


def normalize_change_request_payload(
    target_type: str,
    payload: dict[str, Any] | None,
    *,
    normalize_sandbox_file_payload_fn,
    make_json_compatible_fn,
    http_exception_cls,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise http_exception_cls(status_code=400, detail="proposed_payload must be a JSON object")
    if target_type == "sandbox_file":
        return normalize_sandbox_file_payload_fn(payload)
    return make_json_compatible_fn(payload)


def fetch_sandbox_file_state(
    target_key: str,
    *,
    resolve_sandbox_change_path_fn,
    file_encoding: str,
    content_limit_bytes: int,
    http_exception_cls,
) -> dict[str, Any]:
    path = resolve_sandbox_change_path_fn(target_key)
    if path.exists() and path.is_dir():
        raise http_exception_cls(status_code=400, detail=f"sandbox_file target points to a directory: {target_key}")
    if not path.exists():
        return {"exists": False, "content": "", "encoding": file_encoding}
    size_bytes = path.stat().st_size
    if size_bytes > content_limit_bytes:
        raise http_exception_cls(
            status_code=400,
            detail=f"sandbox_file target exceeds {content_limit_bytes} bytes: {target_key}",
        )
    try:
        content = path.read_text(encoding=file_encoding)
    except UnicodeDecodeError as exc:
        raise http_exception_cls(
            status_code=400,
            detail=f"sandbox_file target is not valid {file_encoding}: {target_key}",
        ) from exc
    return {"exists": True, "content": content, "encoding": file_encoding}


def get_redis_monitor_stats(*, get_redis_client_fn) -> dict[str, int]:
    client = get_redis_client_fn()
    if client is None:
        return {"queue_depth": 0, "active_claims": 0}

    try:
        queue_depth = int(client.llen("task_queue"))
    except Exception:
        queue_depth = 0

    active_claims = 0
    try:
        for _ in client.scan_iter(match="task_claim:*", count=100):
            active_claims += 1
    except Exception:
        active_claims = 0

    return {"queue_depth": queue_depth, "active_claims": active_claims}
