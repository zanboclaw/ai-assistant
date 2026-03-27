from __future__ import annotations

from apps.worker.deliverable_runtime import build_failed_recovery_action, build_runtime_failure_recovery_action


def decide_recovery_action(*, error_message: str, validation_failed: bool) -> dict:
    if validation_failed:
        return build_failed_recovery_action(error_message)
    return build_runtime_failure_recovery_action(error_message)
