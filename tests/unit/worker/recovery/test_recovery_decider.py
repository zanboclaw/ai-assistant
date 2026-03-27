from apps.worker.runtime.recovery.recovery_decider import decide_recovery_action


def test_recovery_decider_uses_runtime_failure_path(monkeypatch):
    monkeypatch.setattr(
        "apps.worker.runtime.recovery.recovery_decider.build_runtime_failure_recovery_action",
        lambda error: {"action": "fallback_provider", "reason": error},
    )
    monkeypatch.setattr(
        "apps.worker.runtime.recovery.recovery_decider.build_failed_recovery_action",
        lambda error: {"action": "retry_current_step", "reason": error},
    )

    payload = decide_recovery_action(error_message="planner timeout", validation_failed=False)

    assert payload["action"] == "fallback_provider"

