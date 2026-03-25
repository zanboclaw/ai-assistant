from session_runtime import compute_session_health


def test_compute_session_health_counts_waiting_clarification_as_active():
    health = compute_session_health(
        task_rows=[
            {
                "id": 1,
                "status": "waiting_clarification",
                "updated_at": "2026-03-25T00:00:00+00:00",
            }
        ],
        memory_rows=[],
        session_state_row=None,
        review_rows=[],
    )

    assert health["active_task_count"] == 1
    assert health["needs_review"] is True
    assert any(item["action"] == "create_review" for item in health["recommended_actions"])
