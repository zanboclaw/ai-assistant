from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse


def get_step_approval(cur, task_id: int, step_order: int, *, ensure_approvals_table) -> Optional[dict]:
    ensure_approvals_table(cur)
    cur.execute(
        """
        SELECT
            id,
            task_id,
            step_order,
            step_name,
            tool_name,
            input_payload,
            reason,
            status,
            decision_note
        FROM approvals
        WHERE task_id = %s AND step_order = %s
        ORDER BY id DESC
        LIMIT 1;
        """,
        (task_id, step_order),
    )
    return cur.fetchone()


def create_step_approval(
    cur,
    task_id: int,
    step_order: int,
    step_name: str,
    tool_name: str,
    input_payload: Any,
    reason: str,
    *,
    ensure_approvals_table,
    safe_json_dumps,
):
    ensure_approvals_table(cur)
    cur.execute(
        """
        INSERT INTO approvals (
            task_id, step_order, step_name, tool_name, input_payload, reason, status
        )
        VALUES (%s, %s, %s, %s, %s, %s, 'pending');
        """,
        (task_id, step_order, step_name, tool_name, safe_json_dumps(input_payload), reason),
    )


def set_step_waiting_approval(
    cur,
    task_id: int,
    step_order: int,
    tool_name: str,
    input_payload: Any,
    reason: str,
    *,
    set_step_result,
):
    set_step_result(
        cur,
        task_id,
        step_order,
        status="waiting_approval",
        tool_name=tool_name,
        input_payload=input_payload,
        output_payload=f"等待审批：{reason}",
        output_data={"approval_required": True, "reason": reason},
        error_message="",
        error_strategy="fail",
    )


def should_require_approval(
    tool_name: str,
    payload: dict,
    *,
    load_risk_policy_settings,
    get_tool_registry_entry,
    low_risk_write_extensions: set[str],
    sensitive_write_extensions: set[str],
    sensitive_write_basenames: set[str],
) -> tuple[bool, str]:
    settings = load_risk_policy_settings()
    registry_entry = get_tool_registry_entry(tool_name)
    if registry_entry and bool(registry_entry.get("approval_required")):
        provider_type = str(registry_entry.get("provider_type") or "builtin")
        return True, f"{tool_name} 已配置 approval_required=true，需要人工审批（provider_type={provider_type}）"

    if tool_name == "shell_exec":
        command = str(payload.get("command") or "").strip()
        return True, f"shell_exec 属于高风险执行工具: {command or '(empty)'}"

    if tool_name in {"file_write", "write_json"}:
        runtime_low_risk_extensions = {str(item).lower() for item in settings.get("approval_low_risk_write_extensions", sorted(low_risk_write_extensions)) if str(item).strip()}
        runtime_sensitive_extensions = {str(item).lower() for item in settings.get("approval_sensitive_write_extensions", sorted(sensitive_write_extensions)) if str(item).strip()}
        runtime_sensitive_basenames = {str(item).lower() for item in settings.get("approval_sensitive_write_basenames", sorted(sensitive_write_basenames)) if str(item).strip()}
        require_existing_file_overwrite = bool(settings.get("approval_require_for_existing_file_overwrite", True))
        require_hidden_files = bool(settings.get("approval_require_for_hidden_files", True))

        path_str = str(payload.get("path") or "").strip()
        if not path_str:
            return True, f"{tool_name} 缺少有效 path，需要人工审批"

        path = Path(path_str)
        suffix = path.suffix.lower()
        basename = path.name.lower()

        if basename in runtime_sensitive_basenames or suffix in runtime_sensitive_extensions:
            return True, f"{tool_name} 将写入脚本/配置文件: {path_str}"

        if require_existing_file_overwrite and path.exists():
            return True, f"{tool_name} 将覆盖现有文件: {path_str}"

        if require_hidden_files and basename.startswith("."):
            return True, f"{tool_name} 将写入隐藏文件: {path_str}"

        if suffix and suffix not in runtime_low_risk_extensions:
            return True, f"{tool_name} 将写入未列入低风险清单的文件类型: {path_str}"

        return False, ""

    if tool_name == "http_request":
        method = str(payload.get("method", "")).upper().strip()
        url = str(payload.get("url") or "").strip()
        allowed_http_methods = {str(item).upper() for item in settings.get("approval_allowed_http_methods", ["GET"]) if str(item).strip()}
        if method not in allowed_http_methods:
            return True, f"http_request {method or 'UNKNOWN'} 需要人工审批"

        parsed = urlparse(url)
        hostname = (parsed.hostname or "").strip().lower()
        approval_suffixes = tuple(
            str(item).lower()
            for item in settings.get("approval_http_get_requires_approval_suffixes", [".local"])
            if str(item).strip()
        )
        if approval_suffixes and hostname.endswith(approval_suffixes):
            return True, f"http_request GET 目标域名需要人工审批: {hostname}"

    return False, ""
