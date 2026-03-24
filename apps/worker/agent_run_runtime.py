from __future__ import annotations

from pathlib import Path
from typing import Any


def process_agent_run(
    agent_run: dict,
    *,
    logger,
    get_conn,
    ensure_agent_tables,
    ensure_evaluator_tables,
    ensure_task_steps_columns,
    ensure_audit_logs_table,
    parse_jsonish,
    build_task_display_input_excerpt,
    build_task_result_excerpt,
    tool_shell_exec,
    tool_file_read,
    tool_read_json,
    tool_json_extract,
    tool_list_dir,
    create_agent_artifact,
    create_agent_message,
    insert_audit_log,
    maybe_refresh_task_runtime_manager_rollup,
    auto_stage5_runtime_execution_mode: str,
    mainline_specialist_tool_profiles: set[str],
    restricted_specialist_subtask_type: str,
):
    agent_run_id = int(agent_run["id"])
    task_id = int(agent_run["task_run_id"])
    execution_mode = str(agent_run.get("execution_mode") or "").strip()
    tool_profile = str(agent_run.get("assigned_tool_profile") or "").strip()
    execution_request = parse_jsonish(agent_run.get("execution_request_json"), {})
    assigned_step_orders = parse_jsonish(agent_run.get("assigned_step_orders_json"), [])

    if agent_run.get("role") != "specialist":
        logger.info("skip non-specialist agent run id=%s", agent_run_id)
        return
    if execution_mode not in {"worker_readonly_v1", auto_stage5_runtime_execution_mode} or tool_profile not in mainline_specialist_tool_profiles:
        logger.info("skip unsupported agent run id=%s mode=%s tool_profile=%s", agent_run_id, execution_mode, tool_profile)
        return

    conn = get_conn()
    cur = conn.cursor()
    try:
        ensure_agent_tables(cur)
        ensure_evaluator_tables(cur)
        ensure_task_steps_columns(cur)
        ensure_audit_logs_table(cur)

        cur.execute("SELECT * FROM task_runs WHERE id = %s;", (task_id,))
        task_row = cur.fetchone()
        if not task_row:
            raise RuntimeError(f"task not found for agent run {agent_run_id}")
        checkpoint_path = str(task_row.get("checkpoint_path") or "").strip()

        cur.execute(
            """
            SELECT step_order, step_name, status, tool_name, input_payload, output_payload, error_message
            FROM task_steps
            WHERE task_id = %s
            ORDER BY step_order ASC;
            """,
            (task_id,),
        )
        step_rows = list(cur.fetchall())

        subtask_type = str(execution_request.get("subtask_type") or "readonly_step_digest").strip() or "readonly_step_digest"
        assigned_step_order_set = {int(item) for item in assigned_step_orders} if assigned_step_orders else set()
        selected_steps = [
            {
                "step_order": int(row["step_order"]),
                "step_name": row["step_name"],
                "status": row["status"],
                "tool_name": row.get("tool_name") or "",
                "input_excerpt": str(row.get("input_payload") or "")[:180],
                "output_excerpt": str(row.get("output_payload") or "")[:220],
                "error_excerpt": str(row.get("error_message") or "")[:160],
            }
            for row in step_rows
            if not assigned_step_order_set or int(row["step_order"]) in assigned_step_order_set
        ]
        if not selected_steps:
            selected_steps = [
                {
                    "step_order": 0,
                    "step_name": "task-result-fallback",
                    "status": task_row.get("status") or "unknown",
                    "tool_name": "",
                    "input_excerpt": build_task_display_input_excerpt(task_row),
                    "output_excerpt": build_task_result_excerpt(task_row),
                    "error_excerpt": str(task_row.get("error_message") or "")[:160],
                }
            ]

        completed_names = [str(item.get("step_name") or "") for item in selected_steps if item.get("status") == "completed"]
        failed_names = [str(item.get("step_name") or "") for item in selected_steps if item.get("status") == "failed"]
        pending_names = [str(item.get("step_name") or "") for item in selected_steps if item.get("status") not in {"completed", "failed"}]

        cur.execute(
            """
            UPDATE agent_runs
            SET status = 'running',
                started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                completed_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
            """,
            (agent_run_id,),
        )
        create_agent_message(
            cur,
            task_id,
            agent_run_id,
            "specialist",
            "manager",
            "progress",
            {
                "execution_mode": execution_mode,
                "status": "running",
                "summary": "worker started specialist execution",
                "assigned_step_orders": assigned_step_orders,
            },
        )

        cur.execute("SELECT id, version FROM agent_artifacts WHERE id = %s;", (agent_run.get("output_artifact_id"),))
        existing_output = cur.fetchone()
        next_version = int(existing_output.get("version") or 1) + 1 if existing_output else 1

        if subtask_type == restricted_specialist_subtask_type:
            source = execution_request.get("source") or {}
            command = str(source.get("command") or "pwd").strip() or "pwd"
            restricted_tools = list(source.get("restricted_tools") or [])
            result = tool_shell_exec(command)
            if not result.get("ok"):
                raise RuntimeError(result.get("error") or "restricted shell probe failed")
            command_output = (result.get("output_data") or {}).get("stdout") or ""
            execution_result = {
                "execution_mode": execution_mode,
                "subtask_type": subtask_type,
                "status": "completed",
                "request_snapshot": execution_request,
                "restricted_tool_profile": tool_profile,
                "restricted_tools": restricted_tools,
                "probe_command": command,
                "probe_result": {
                    "returncode": int(((result.get("output_data") or {}).get("returncode")) or 0),
                    "stdout_excerpt": str(command_output)[:400],
                },
                "observations": [
                    f"restricted_tools={','.join(restricted_tools) if restricted_tools else '(none)'}",
                    f"probe_command={command}",
                ],
            }
            draft_payload = {
                "protocol_version": "multi-agent-v1",
                "task_id": task_id,
                "agent_run_id": agent_run_id,
                "summary": "worker executed restricted shell probe",
                "output": {
                    "slot": execution_request.get("slot"),
                    "objective": execution_request.get("objective") or "",
                    "subtask": {
                        "type": subtask_type,
                        "execution_mode": execution_mode,
                        "assigned_step_orders": assigned_step_orders,
                    },
                    "execution_request": execution_request,
                    "execution_result": execution_result,
                },
            }
            result_summary = "worker specialist restricted shell probe completed"
        elif subtask_type == "readonly_source_snapshot":
            source = execution_request.get("source") or {}
            source_kind = str(source.get("kind") or "").strip()
            source_path = str(source.get("path") or "").strip()
            source_json_path = str(source.get("json_path") or "").strip()
            dir_limit = max(1, min(int(source.get("dir_limit") or 20), 200))
            source_result: dict[str, Any]
            if source_kind == "text_file":
                result = tool_file_read(source_path)
                if not result.get("ok"):
                    raise RuntimeError(result.get("error") or "text_file snapshot failed")
                raw_text = str(((result.get("output_data") or {}).get("raw_text")) or "")
                excerpt = raw_text[:400]
                source_result = {
                    "kind": source_kind,
                    "path": source_path,
                    "excerpt": excerpt,
                    "char_count": len(raw_text),
                }
                observations = [
                    f"text_file chars={len(raw_text)}",
                    f"excerpt={excerpt[:120]}",
                ]
            elif source_kind == "json_file":
                result = tool_read_json(source_path)
                if not result.get("ok"):
                    raise RuntimeError(result.get("error") or "json_file snapshot failed")
                parsed_json = ((result.get("output_data") or {}).get("json"))
                extracted_value = parsed_json
                if source_json_path:
                    extract_result = tool_json_extract(parsed_json, source_json_path)
                    if not extract_result.get("ok"):
                        raise RuntimeError(extract_result.get("error") or "json_extract failed")
                    extracted_value = (extract_result.get("output_data") or {}).get("value")
                source_result = {
                    "kind": source_kind,
                    "path": source_path,
                    "json_path": source_json_path,
                    "selected_value": extracted_value,
                }
                observations = [
                    f"json_file path={source_path}",
                    f"json_path={source_json_path or '(root)'}",
                ]
            elif source_kind == "directory":
                result = tool_list_dir(source_path)
                if not result.get("ok"):
                    raise RuntimeError(result.get("error") or "directory snapshot failed")
                entries = list(((result.get("output_data") or {}).get("entries")) or [])[:dir_limit]
                source_result = {
                    "kind": source_kind,
                    "path": source_path,
                    "entries": entries,
                    "entry_count": len(entries),
                }
                observations = [
                    f"directory entries={len(entries)}",
                    *(entries[:3]),
                ]
            else:
                raise RuntimeError(f"unsupported readonly_source_snapshot kind: {source_kind}")

            execution_result = {
                "execution_mode": execution_mode,
                "subtask_type": subtask_type,
                "status": "completed",
                "request_snapshot": execution_request,
                "source": source_result,
                "observations": observations,
            }
            draft_payload = {
                "protocol_version": "multi-agent-v1",
                "task_id": task_id,
                "agent_run_id": agent_run_id,
                "summary": "worker executed readonly source snapshot",
                "output": {
                    "slot": execution_request.get("slot"),
                    "objective": execution_request.get("objective") or "",
                    "subtask": {
                        "type": subtask_type,
                        "execution_mode": execution_mode,
                        "assigned_step_orders": assigned_step_orders,
                    },
                    "execution_request": execution_request,
                    "execution_result": execution_result,
                },
            }
            result_summary = "worker specialist readonly source snapshot completed"
        elif subtask_type == "readonly_task_snapshot":
            latest_evaluator = {}
            cur.execute(
                """
                SELECT decision, score, failure_reason, failure_stage, recommendation, proposal_json, created_at
                FROM evaluator_runs
                WHERE task_run_id = %s
                ORDER BY id DESC
                LIMIT 1;
                """,
                (task_id,),
            )
            evaluator_row = cur.fetchone()
            if evaluator_row:
                latest_evaluator = {
                    "decision": evaluator_row.get("decision") or "",
                    "score": int(evaluator_row.get("score") or 0),
                    "failure_reason": evaluator_row.get("failure_reason") or "none",
                    "failure_stage": evaluator_row.get("failure_stage") or "none",
                    "recommendation": evaluator_row.get("recommendation") or "",
                    "workflow_proposal": parse_jsonish(evaluator_row.get("proposal_json"), {}),
                    "created_at": evaluator_row.get("created_at").isoformat() if evaluator_row.get("created_at") else None,
                }

            latest_review = {}
            cur.execute(
                """
                SELECT content_json, version, created_at
                FROM agent_artifacts
                WHERE task_run_id = %s AND artifact_type = 'review'
                ORDER BY id DESC
                LIMIT 1;
                """,
                (task_id,),
            )
            review_row = cur.fetchone()
            if review_row:
                review_content = parse_jsonish(review_row.get("content_json"), {})
                latest_review = {
                    "decision": review_content.get("decision") or "",
                    "quality_score": review_content.get("quality_score"),
                    "failure_reason": review_content.get("failure_reason") or "none",
                    "failure_stage": review_content.get("failure_stage") or "none",
                    "version": int(review_row.get("version") or 1),
                    "created_at": review_row.get("created_at").isoformat() if review_row.get("created_at") else None,
                }

            checkpoint_summary = {
                "exists": bool(checkpoint_path),
                "path": checkpoint_path,
            }
            if checkpoint_path:
                checkpoint_summary["label"] = Path(checkpoint_path).name

            execution_result = {
                "execution_mode": execution_mode,
                "subtask_type": subtask_type,
                "status": "completed",
                "request_snapshot": execution_request,
                "task_snapshot": {
                    "task_status": task_row.get("status") or "unknown",
                    "result_excerpt": str(task_row.get("result") or "")[:280],
                    "error_excerpt": str(task_row.get("error_message") or "")[:200],
                    "checkpoint": checkpoint_summary,
                    "step_status_counts": {
                        "completed": len(completed_names),
                        "failed": len(failed_names),
                        "other": len(pending_names),
                    },
                },
                "latest_evaluator": latest_evaluator,
                "latest_review": latest_review,
                "observations": [
                    f"task status={task_row.get('status') or 'unknown'}",
                    f"checkpoint={'yes' if checkpoint_path else 'no'}",
                    f"completed_steps={len(completed_names)} failed_steps={len(failed_names)}",
                ],
            }
            draft_payload = {
                "protocol_version": "multi-agent-v1",
                "task_id": task_id,
                "agent_run_id": agent_run_id,
                "summary": "worker executed readonly task snapshot",
                "output": {
                    "slot": execution_request.get("slot"),
                    "objective": execution_request.get("objective") or "",
                    "subtask": {
                        "type": subtask_type,
                        "execution_mode": execution_mode,
                        "assigned_step_orders": assigned_step_orders,
                    },
                    "execution_request": execution_request,
                    "execution_result": execution_result,
                },
            }
            result_summary = "worker specialist readonly task snapshot completed"
        else:
            draft_payload = {
                "protocol_version": "multi-agent-v1",
                "task_id": task_id,
                "agent_run_id": agent_run_id,
                "summary": "worker executed readonly specialist subtask",
                "output": {
                    "slot": execution_request.get("slot"),
                    "objective": execution_request.get("objective") or "",
                    "subtask": {
                        "type": subtask_type,
                        "execution_mode": execution_mode,
                        "assigned_step_orders": assigned_step_orders,
                    },
                    "execution_request": execution_request,
                    "execution_result": {
                        "execution_mode": execution_mode,
                        "subtask_type": subtask_type,
                        "status": "completed",
                        "request_snapshot": execution_request,
                        "assigned_step_orders": assigned_step_orders,
                        "completed_step_names": completed_names[:6],
                        "failed_step_names": failed_names[:6],
                        "pending_step_names": pending_names[:6],
                        "observations": [
                            f"step#{int(item.get('step_order') or 0)} {item.get('step_name') or ''} -> {item.get('status') or 'unknown'}"
                            for item in selected_steps[:4]
                        ],
                    },
                },
            }
            result_summary = "worker specialist readonly digest completed"
        draft_artifact_id = create_agent_artifact(
            cur,
            task_id,
            agent_run_id,
            "draft",
            "worker specialist draft",
            draft_payload,
            version=next_version,
        )
        create_agent_message(
            cur,
            task_id,
            agent_run_id,
            "specialist",
            "manager",
            "result",
            {
                "execution_mode": execution_mode,
                "status": "completed",
                "artifact_ids": [draft_artifact_id],
                "summary": result_summary,
            },
        )
        cur.execute(
            """
            UPDATE agent_runs
            SET status = 'completed',
                output_artifact_id = %s,
                completed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP,
                error_summary = ''
            WHERE id = %s;
            """,
            (draft_artifact_id, agent_run_id),
        )
        audit_event_type = "agent.worker_execute_demo"
        if execution_mode == auto_stage5_runtime_execution_mode:
            audit_event_type = "agent.mainline_runtime_execute"
        insert_audit_log(
            cur,
            audit_event_type,
            "worker",
            task_id,
            {
                "agent_run_id": agent_run_id,
                "execution_mode": execution_mode,
                "assigned_step_orders": assigned_step_orders,
            },
        )
        if execution_mode == auto_stage5_runtime_execution_mode:
            maybe_refresh_task_runtime_manager_rollup(cur, task_id)
        conn.commit()
        logger.info("worker processed agent run id=%s task_id=%s", agent_run_id, task_id)
    except Exception as exc:
        conn.rollback()
        try:
            cur.execute(
                """
                UPDATE agent_runs
                SET status = 'failed',
                    error_summary = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
                """,
                (str(exc), agent_run_id),
            )
            audit_event_type = "agent.worker_execute_failed"
            if execution_mode == auto_stage5_runtime_execution_mode:
                audit_event_type = "agent.mainline_runtime_execute_failed"
            insert_audit_log(
                cur,
                audit_event_type,
                "worker",
                task_id,
                {"agent_run_id": agent_run_id, "error": str(exc)},
            )
            conn.commit()
        except Exception:
            conn.rollback()
        logger.exception("agent run failed id=%s error=%s", agent_run_id, exc)
    finally:
        cur.close()
        conn.close()
