from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import APIRouter, Header, HTTPException

from schemas import ApprovalDecision, TaskClarifyRequest, TaskInterruptRequest, TaskResumeRequest


def get_approval_or_404(cur, approval_id: int):
    cur.execute(
        """
        SELECT id, task_id, step_order, status
        FROM approvals
        WHERE id = %s;
        """,
        (approval_id,),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Approval not found")
    return row


def resolve_recovery_action_resume_step(
    cur,
    task_id: int,
    task: dict[str, Any],
    action: str,
    *,
    resolve_resume_from_step: Callable[[Any, int, int | None], int],
) -> int:
    action_key = str(action or "").strip()
    if action_key == "retry_generate":
        cur.execute(
            """
            SELECT step_order
            FROM task_steps
            WHERE task_id = %s AND tool_name = 'generate_text'
            ORDER BY step_order ASC
            LIMIT 1;
            """,
            (task_id,),
        )
        row = cur.fetchone()
        return int((row or {}).get("step_order") or task.get("current_step") or 1)
    if action_key == "retry":
        return resolve_resume_from_step(cur, task_id, task.get("current_step"))
    if action_key == "replan":
        return 1
    raise HTTPException(status_code=400, detail=f"Recovery action {action_key or '(empty)'} is not directly executable")


def register_task_control_routes(
    *,
    get_conn: Callable[[], Any],
    require_actor_permission: Callable[[Any, str | None, str], dict[str, Any]],
    get_task_or_404: Callable[[Any, int], dict[str, Any]],
    update_checkpoint_status: Callable[[str | None, str, str], None],
    insert_audit_log: Callable[[Any, str, str, int | None, Any | None], None],
    resolve_resume_from_step: Callable[[Any, int, int | None], int],
    reset_task_for_resume: Callable[..., None],
    reset_task_for_clarification: Callable[..., None],
    enqueue_task: Callable[[int], None],
    parse_maybe_json: Callable[[Any], Any],
    extract_task_clarification_state: Callable[[dict[str, Any], str], tuple[str, list[dict[str, Any]]]],
    build_clarified_user_input: Callable[[str, list[dict[str, Any]]], str],
    infer_task_intent: Callable[..., dict[str, Any]],
    build_task_display_user_input: Callable[[str, dict[str, Any] | None], str],
    infer_deliverable_spec: Callable[[str, dict[str, Any]], dict[str, Any]],
    logger: Any,
):
    router = APIRouter()

    @router.post("/tasks/{task_id}/interrupt")
    def interrupt_task(
        task_id: int,
        request: TaskInterruptRequest,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        actor = require_actor_permission(cur, x_actor_name, "operate")

        task = get_task_or_404(cur, task_id)
        current_status = str(task["status"] or "")
        if current_status in {"completed", "failed"}:
            cur.close()
            conn.close()
            raise HTTPException(status_code=400, detail="Completed or failed tasks cannot be interrupted")

        if current_status in {"paused", "interrupt_requested"}:
            cur.close()
            conn.close()
            raise HTTPException(status_code=400, detail="Task is already paused or interrupt requested")

        note = request.note.strip() or "manual interrupt requested"
        next_status = "interrupt_requested" if current_status == "running" else "paused"

        cur.execute(
            """
            UPDATE task_runs
            SET status = %s,
                error_message = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
            """,
            (next_status, note, task_id),
        )

        update_checkpoint_status(task.get("checkpoint_path"), next_status if next_status != "interrupt_requested" else "running", note)
        insert_audit_log(
            cur,
            "task.interrupt",
            actor["actor_name"],
            task_id,
            {
                "previous_status": current_status,
                "next_status": next_status,
                "note": note,
                "role": actor["role"],
            },
        )

        conn.commit()
        cur.close()
        conn.close()

        logger.info(
            "task interrupt requested id=%s actor=%s previous_status=%s next_status=%s note=%s",
            task_id,
            actor["actor_name"],
            current_status,
            next_status,
            note[:200],
        )
        return {"message": "task interrupt requested", "task_id": task_id, "status": next_status}

    @router.post("/tasks/{task_id}/resume")
    def resume_task(
        task_id: int,
        request: TaskResumeRequest,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        actor = require_actor_permission(cur, x_actor_name, "operate")

        task = get_task_or_404(cur, task_id)
        if task["status"] not in {"failed", "waiting_approval", "paused", "interrupt_requested"}:
            cur.close()
            conn.close()
            raise HTTPException(
                status_code=400,
                detail="Only failed, paused, interrupt_requested, or waiting_approval tasks can be resumed",
            )

        cur.execute(
            """
            SELECT id
            FROM approvals
            WHERE task_id = %s AND status = 'pending'
            ORDER BY id DESC;
            """,
            (task_id,),
        )
        pending_approvals = cur.fetchall()
        if pending_approvals:
            cur.close()
            conn.close()
            raise HTTPException(status_code=400, detail="Task has pending approvals; approve or reject them first")

        resume_from = resolve_resume_from_step(cur, task_id, request.from_step or task.get("current_step"))
        reset_task_for_resume(
            cur,
            task_id=task_id,
            task=task,
            resume_from=resume_from,
            actor=actor,
            note=request.note.strip(),
            event_type="task.resume",
        )

        conn.commit()
        cur.close()
        conn.close()

        enqueue_task(task_id)
        update_checkpoint_status(task.get("checkpoint_path"), "pending", request.note.strip() or "task resumed")
        logger.info(
            "task resumed id=%s actor=%s from_step=%s note=%s previous_status=%s",
            task_id,
            actor["actor_name"],
            resume_from,
            request.note[:200],
            task["status"],
        )
        return {"message": "task resumed", "task_id": task_id, "from_step": resume_from}

    @router.post("/tasks/{task_id}/apply-recovery-action")
    def apply_recovery_action(
        task_id: int,
        request: TaskResumeRequest,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        actor = require_actor_permission(cur, x_actor_name, "operate")

        task = get_task_or_404(cur, task_id)
        if task["status"] not in {"failed", "paused"}:
            cur.close()
            conn.close()
            raise HTTPException(status_code=400, detail="Only failed or paused tasks can apply recovery action")

        cur.execute(
            """
            SELECT recovery_action_json
            FROM task_runs
            WHERE id = %s;
            """,
            (task_id,),
        )
        action_row = cur.fetchone() or {}
        recovery_action = parse_maybe_json(action_row.get("recovery_action_json")) or {}
        action_key = str(recovery_action.get("action") or "").strip()
        if not action_key or action_key == "none":
            cur.close()
            conn.close()
            raise HTTPException(status_code=400, detail="Task has no actionable recovery action")

        cur.execute(
            """
            SELECT id
            FROM approvals
            WHERE task_id = %s AND status = 'pending'
            ORDER BY id DESC;
            """,
            (task_id,),
        )
        if cur.fetchall():
            cur.close()
            conn.close()
            raise HTTPException(status_code=400, detail="Task has pending approvals; approve or reject them first")

        resume_from = resolve_recovery_action_resume_step(
            cur,
            task_id,
            task,
            action_key,
            resolve_resume_from_step=resolve_resume_from_step,
        )
        if request.from_step is not None:
            resume_from = int(request.from_step)

        reset_task_for_resume(
            cur,
            task_id=task_id,
            task=task,
            resume_from=resume_from,
            actor=actor,
            note=request.note.strip() or f"apply recovery action: {action_key}",
            event_type="task.apply_recovery_action",
            details={
                "recovery_action": action_key,
            },
        )

        conn.commit()
        cur.close()
        conn.close()

        enqueue_task(task_id)
        update_checkpoint_status(
            task.get("checkpoint_path"),
            "pending",
            request.note.strip() or f"apply recovery action: {action_key}",
        )
        logger.info(
            "task recovery action applied id=%s actor=%s action=%s from_step=%s previous_status=%s",
            task_id,
            actor["actor_name"],
            action_key,
            resume_from,
            task["status"],
        )
        return {
            "message": "task recovery action applied",
            "task_id": task_id,
            "action": action_key,
            "from_step": resume_from,
        }

    @router.post("/tasks/{task_id}/clarify")
    def clarify_task(
        task_id: int,
        request: TaskClarifyRequest,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        clarification = request.clarification.strip()
        if not clarification:
            raise HTTPException(status_code=400, detail="Clarification cannot be empty")

        conn = get_conn()
        cur = conn.cursor()
        actor = require_actor_permission(cur, x_actor_name, "operate")

        cur.execute(
            """
            SELECT
                id,
                status,
                current_step,
                checkpoint_path,
                error_message,
                user_input,
                runtime_overrides,
                recovery_action_json
            FROM task_runs
            WHERE id = %s;
            """,
            (task_id,),
        )
        task = cur.fetchone()
        if not task:
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail="Task not found")

        if task["status"] not in {"failed", "paused"}:
            cur.close()
            conn.close()
            raise HTTPException(status_code=400, detail="Only failed or paused tasks can be clarified")

        recovery_action = parse_maybe_json(task.get("recovery_action_json")) or {}
        action_key = str(recovery_action.get("action") or "").strip()
        if action_key != "clarify":
            cur.close()
            conn.close()
            raise HTTPException(status_code=400, detail="Task does not require clarify action")

        cur.execute(
            """
            SELECT id
            FROM approvals
            WHERE task_id = %s AND status = 'pending'
            ORDER BY id DESC;
            """,
            (task_id,),
        )
        if cur.fetchall():
            cur.close()
            conn.close()
            raise HTTPException(status_code=400, detail="Task has pending approvals; approve or reject them first")

        runtime_overrides = parse_maybe_json(task.get("runtime_overrides")) or {}
        skill_invocation = runtime_overrides.get("skill_invocation") or {}
        skill_id = str(skill_invocation.get("skill_id") or "").strip() or None
        original_input, clarification_history = extract_task_clarification_state(
            runtime_overrides,
            fallback_user_input=str(task.get("user_input") or ""),
        )
        clarification_entry = {
            "clarification": clarification[:4000],
            "note": request.note.strip()[:400],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        new_history = [*clarification_history, clarification_entry]
        effective_runtime_overrides = dict(runtime_overrides)
        effective_runtime_overrides["clarification_state"] = {
            "original_user_input": original_input,
            "history": new_history,
        }
        new_user_input = build_clarified_user_input(original_input, new_history)
        task_intent = infer_task_intent(new_user_input, skill_id=skill_id)
        task_intent["goal_summary"] = build_task_display_user_input(new_user_input, effective_runtime_overrides)[:160]
        deliverable_spec = infer_deliverable_spec(new_user_input, task_intent)

        reset_task_for_clarification(
            cur,
            task_id=task_id,
            task=task,
            actor=actor,
            new_user_input=new_user_input,
            task_intent=task_intent,
            deliverable_spec=deliverable_spec,
            runtime_overrides=effective_runtime_overrides,
            note=request.note.strip() or "clarify task and replan",
            details={
                "clarification": clarification[:1000],
                "recovery_action": action_key,
                "clarification_count": len(new_history),
            },
        )

        conn.commit()
        cur.close()
        conn.close()

        enqueue_task(task_id)
        update_checkpoint_status(task.get("checkpoint_path"), "pending", request.note.strip() or "clarify task and replan")
        logger.info(
            "task clarified id=%s actor=%s previous_status=%s clarification=%s",
            task_id,
            actor["actor_name"],
            task["status"],
            clarification[:200],
        )
        return {
            "message": "task clarified and resumed",
            "task_id": task_id,
            "action": "clarify",
            "from_step": 1,
        }

    @router.get("/tasks/{task_id}/approvals")
    def list_task_approvals(task_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")

        cur.execute("SELECT id FROM task_runs WHERE id = %s;", (task_id,))
        task_exists = cur.fetchone()
        if not task_exists:
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail="Task not found")

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
                decision_note,
                created_at,
                updated_at,
                decided_at
            FROM approvals
            WHERE task_id = %s
            ORDER BY id DESC;
            """,
            (task_id,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return rows

    @router.get("/approvals")
    def list_approvals(status: str | None = None, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")

        if status:
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
                    decision_note,
                    created_at,
                    updated_at,
                    decided_at
                FROM approvals
                WHERE status = %s
                ORDER BY id DESC;
                """,
                (status,),
            )
        else:
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
                    decision_note,
                    created_at,
                    updated_at,
                    decided_at
                FROM approvals
                ORDER BY id DESC;
                """
            )

        rows = cur.fetchall()
        cur.close()
        conn.close()
        return rows

    @router.post("/approvals/{approval_id}/approve")
    def approve_approval(
        approval_id: int,
        decision: ApprovalDecision,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        actor = require_actor_permission(cur, x_actor_name, "operate")

        approval = get_approval_or_404(cur, approval_id)
        if approval["status"] != "pending":
            cur.close()
            conn.close()
            raise HTTPException(status_code=400, detail="Approval is not pending")

        cur.execute(
            """
            UPDATE approvals
            SET status = 'approved',
                decision_note = %s,
                updated_at = CURRENT_TIMESTAMP,
                decided_at = CURRENT_TIMESTAMP
            WHERE id = %s;
            """,
            (decision.note, approval_id),
        )

        cur.execute(
            """
            UPDATE task_steps
            SET status = 'pending',
                error_message = '',
                updated_at = CURRENT_TIMESTAMP
            WHERE task_id = %s AND step_order = %s;
            """,
            (approval["task_id"], approval["step_order"]),
        )

        cur.execute(
            """
            UPDATE task_runs
            SET status = 'pending',
                error_message = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
            """,
            (approval["task_id"],),
        )

        insert_audit_log(
            cur,
            "approval.approve",
            actor["actor_name"],
            approval["task_id"],
            {
                "approval_id": approval_id,
                "step_order": approval["step_order"],
                "decision_note": decision.note,
                "role": actor["role"],
            },
        )

        conn.commit()
        cur.close()
        conn.close()
        enqueue_task(int(approval["task_id"]))
        logger.info(
            "approval approved approval_id=%s task_id=%s step_order=%s actor=%s note=%s",
            approval_id,
            approval["task_id"],
            approval["step_order"],
            actor["actor_name"],
            decision.note[:200],
        )
        return {"message": "approval approved", "approval_id": approval_id}

    @router.post("/approvals/{approval_id}/reject")
    def reject_approval(
        approval_id: int,
        decision: ApprovalDecision,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        actor = require_actor_permission(cur, x_actor_name, "operate")

        approval = get_approval_or_404(cur, approval_id)
        if approval["status"] != "pending":
            cur.close()
            conn.close()
            raise HTTPException(status_code=400, detail="Approval is not pending")

        note = decision.note.strip() or "审批拒绝"

        cur.execute(
            """
            UPDATE approvals
            SET status = 'rejected',
                decision_note = %s,
                updated_at = CURRENT_TIMESTAMP,
                decided_at = CURRENT_TIMESTAMP
            WHERE id = %s;
            """,
            (note, approval_id),
        )

        cur.execute(
            """
            UPDATE task_steps
            SET status = 'failed',
                output_payload = %s,
                error_message = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE task_id = %s AND step_order = %s;
            """,
            (f"审批拒绝：{note}", f"审批拒绝：{note}", approval["task_id"], approval["step_order"]),
        )

        cur.execute(
            """
            UPDATE task_runs
            SET status = 'failed',
                error_message = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
            """,
            (f"审批拒绝：{note}", approval["task_id"]),
        )

        insert_audit_log(
            cur,
            "approval.reject",
            actor["actor_name"],
            approval["task_id"],
            {
                "approval_id": approval_id,
                "step_order": approval["step_order"],
                "decision_note": note,
                "role": actor["role"],
            },
        )

        conn.commit()
        cur.close()
        conn.close()
        logger.info(
            "approval rejected approval_id=%s task_id=%s step_order=%s actor=%s note=%s",
            approval_id,
            approval["task_id"],
            approval["step_order"],
            actor["actor_name"],
            note[:200],
        )
        return {"message": "approval rejected", "approval_id": approval_id}

    return router
