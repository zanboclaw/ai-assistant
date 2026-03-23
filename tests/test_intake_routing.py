from main import attach_task_display_fields, resolve_intake_route_mode


def test_direct_answer_routes_to_fast_path():
    route_mode, route_reason = resolve_intake_route_mode(
        task_intent={"task_type": "question_answer", "needs_clarification": False},
        deliverable_spec={"deliverable_type": "direct_answer", "clarify": {"blocking": False}},
    )

    assert route_mode == "fast_path"
    assert "快速路径" in route_reason


def test_qa_alias_also_routes_to_fast_path():
    route_mode, _route_reason = resolve_intake_route_mode(
        task_intent={"task_type": "qa", "needs_clarification": False},
        deliverable_spec={"deliverable_type": "direct_answer", "clarify": {"blocking": False}},
    )

    assert route_mode == "fast_path"


def test_clarify_blocks_into_clarify_first():
    route_mode, route_reason = resolve_intake_route_mode(
        task_intent={"task_type": "research", "needs_clarification": True},
        deliverable_spec={"deliverable_type": "research_summary", "clarify": {"blocking": True}},
    )

    assert route_mode == "clarify_first"
    assert "clarify" in route_reason


def test_explicit_skill_stays_in_draft_task_mode():
    route_mode, _route_reason = resolve_intake_route_mode(
        task_intent={"task_type": "execute", "needs_clarification": False},
        deliverable_spec={"deliverable_type": "execution_result", "clarify": {"blocking": False}},
        skill_id="repo_inspector",
    )

    assert route_mode == "draft_task"


def test_attach_task_display_fields_extracts_clarification_metadata():
    row = {
        "user_input": "整理发布说明\n\n补充说明：\n以下补充信息已经提供完整，请直接基于这些信息完成任务，\n不要再输出“请提供以下信息”“请补充”等追问语句。",
        "runtime_overrides": {
            "clarification_state": {
                "original_user_input": "整理发布说明",
                "history": [
                    {"clarification": "只覆盖本周变更", "created_at": "2026-03-23T00:00:00+00:00"},
                    {"clarification": "输出中文版本", "created_at": "2026-03-23T00:01:00+00:00"},
                ],
            }
        },
        "result": "最终交付正文\n\n产出文件：artifact.md",
    }

    attach_task_display_fields(row)

    assert row["display_user_input"] == "整理发布说明（已补充澄清 2 次）"
    assert row["original_user_input"] == "整理发布说明"
    assert row["clarification_count"] == 2
    assert row["result_excerpt"] == "最终交付正文"
