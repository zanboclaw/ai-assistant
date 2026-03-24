from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class MockState:
    def __init__(self) -> None:
        self.next_task_id = 200
        self.base_session_id = 11
        self.memories = [
            {
                "id": 1,
                "memory_key": "release-checklist",
                "memory_kind": "pattern_memory",
                "title": "发布回滚 Checklist",
                "content": "先执行 healthcheck，再核对 migration，最后准备 rollback 命令和负责人。",
                "hit_count": 5,
                "metadata": {
                    "matched_keywords": ["发布", "回滚", "checklist"],
                    "match_explanation": "查询和历史发布回滚经验高度相关",
                    "citation_hint": "可在最终交付中引用为上线前检查经验",
                },
            },
            {
                "id": 2,
                "memory_key": "ci-gate",
                "memory_kind": "task_memory",
                "title": "CI 质量门禁",
                "content": "优先保证 py_compile、pytest、Docker build 与前端脚本检查全绿。",
                "hit_count": 3,
                "metadata": {
                    "matched_keywords": ["ci", "pytest", "docker"],
                    "match_explanation": "命中了 CI 与质量门禁相关关键词",
                    "citation_hint": "适合作为工程化改造的历史依据",
                },
            },
        ]
        self.tasks: dict[int, dict[str, Any]] = {}
        self._seed_task()

    def _seed_task(self) -> None:
        task = self._build_task(
            user_input="整理发布与回滚方案",
            route="draft_task",
            result="1. 先执行健康检查\n2. 再确认迁移状态\n3. 最后准备回滚方案",
        )
        self.tasks[int(task["id"])] = task

    def _build_task(self, *, user_input: str, route: str, result: str) -> dict[str, Any]:
        task_id = self.next_task_id
        self.next_task_id += 1
        created_at = utc_now()
        runtime_overrides = {
            "intake": {
                "mode": route,
                "route": route,
                "confirmed_at": created_at,
            },
            "memory_context": {
                "retrieval_query": user_input,
                "retrieved_memories": deepcopy(self.memories[:1]),
            },
        }
        task_intent = {
            "task_type": "question_answer" if route == "fast_path" else "research",
            "goal_summary": user_input[:160],
            "needs_clarification": False,
        }
        deliverable_spec = {
            "deliverable_type": "direct_answer" if route == "fast_path" else "research_summary",
            "acceptance_hints": ["答案要包含下一步动作", "给出引用依据"],
            "clarify": {"blocking": False, "questions": []},
        }
        return {
            "id": task_id,
            "session_id": self.base_session_id,
            "user_input": user_input,
            "display_user_input": user_input,
            "original_user_input": user_input,
            "clarification_count": 0,
            "created_by_actor": "local_admin",
            "status": "completed",
            "current_step": 3,
            "result": result,
            "error_message": "",
            "runtime_overrides": runtime_overrides,
            "task_intent": task_intent,
            "deliverable_spec": deliverable_spec,
            "validation_report": {
                "passed": True,
                "summary": "mock validation passed",
                "checks": [],
            },
            "recovery_action": {"action": "none", "summary": ""},
            "created_at": created_at,
            "updated_at": created_at,
            "stage5": {
                "recommended_action": "finalize",
                "latest_reviewer_decision": "approved",
                "latest_final_artifact": {"version": 1},
                "latest_evaluator": {"decision": "accepted", "score": 0.98, "source": "mock"},
                "latest_workflow_proposal": {},
                "validation_passed": True,
                "recovery_action_key": "none",
                "implementation_status": "mock_runtime",
                "execution_backend": "mock_api",
                "specialist_execution_modes": ["mock"],
                "awaiting_role": "",
                "blocking_reason": "",
            },
        }

    def create_task(self, user_input: str, route: str) -> dict[str, Any]:
        prefix = "快速答复" if route == "fast_path" else "正式任务交付"
        result = f"{prefix}：\n- 输入：{user_input}\n- 结论：这是 mock API 返回的稳定交付。\n- 下一步：可继续查看长期记忆和配额状态。"
        task = self._build_task(user_input=user_input, route=route, result=result)
        self.tasks[int(task["id"])] = task
        return task

    def search_memories(self, query: str) -> list[dict[str, Any]]:
        lowered = query.lower()
        rows: list[dict[str, Any]] = []
        for item in self.memories:
            haystack = f"{item['title']} {item['content']}".lower()
            if any(token in haystack for token in lowered.split() if token):
                rows.append(deepcopy(item))
        if not rows:
            rows = deepcopy(self.memories[:1])
            rows[0]["metadata"]["match_explanation"] = "没有精确命中，返回最近最常用的长期记忆作为兜底。"
        return rows


STATE = MockState()


def json_response(handler: BaseHTTPRequestHandler, payload: Any, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, X-Actor-Name")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
    handler.end_headers()
    handler.wfile.write(body)


class MockApiHandler(BaseHTTPRequestHandler):
    server_version = "MockAIAPI/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_OPTIONS(self) -> None:
        json_response(self, {"ok": True})

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/monitor/overview":
            return json_response(
                self,
                {
                    "task_metrics": {"tasks_by_status": {"completed": len(STATE.tasks)}},
                    "approval_metrics": {"pending_approvals": 0},
                    "queue_metrics": {},
                    "risk_metrics": {},
                    "tool_metrics": {},
                    "model_metrics": {},
                    "agent_metrics": {},
                    "change_metrics": {"total_change_requests": 1, "enforced_target_count": 2},
                    "access_metrics": {"actor_count": 3, "quota_count": 3},
                    "review_metrics": {"daily_reviews_today": 1},
                    "runtime_metadata": {
                        "step_request_protocol_version": "mock-v1",
                        "multi_agent_protocol_version": "mock-v1",
                    },
                    "readiness_metrics": {},
                    "session_metrics": {},
                    "recent_tasks": list(STATE.tasks.values())[:3],
                    "recent_agent_runs": [],
                    "recent_evaluator_runs": [],
                    "recent_reviews": [],
                    "recent_audit_logs": [],
                },
            )
        if path == "/risk-policies":
            return json_response(self, [])
        if path == "/change-requests":
            return json_response(self, [])
        if path == "/access/actors":
            return json_response(
                self,
                [
                    {"actor_name": "local_admin", "role": "admin", "tenant_key": "default", "description": "Admin", "permission_overrides": [], "permissions": ["read", "operate", "admin"]},
                    {"actor_name": "local_operator", "role": "operator", "tenant_key": "default", "description": "Operator", "permission_overrides": [], "permissions": ["read", "operate"]},
                    {"actor_name": "local_viewer", "role": "viewer", "tenant_key": "default", "description": "Viewer", "permission_overrides": [], "permissions": ["read"]},
                ],
            )
        if path == "/access/quota-usage":
            return json_response(
                self,
                [
                    {
                        "actor_name": "local_admin",
                        "role": "admin",
                        "daily_task_count": 2,
                        "daily_task_limit": 50,
                        "active_task_count": 1,
                        "active_task_limit": 10,
                        "daily_remaining": 48,
                        "active_remaining": 9,
                        "daily_token_count": 4000,
                        "daily_token_limit": 500000,
                        "daily_token_remaining": 496000,
                        "max_parallel_agents": 16,
                    }
                ],
            )
        if path == "/skills":
            return json_response(
                self,
                [
                    {
                        "skill_id": "workspace_file_summary",
                        "display_name": "Workspace File Summary",
                        "latest_version": "1.0.0",
                        "status": "active",
                        "entrypoint_kind": "structured_steps",
                        "description": "mock active skill",
                    }
                ],
            )
        if path.startswith("/skills/"):
            skill_id = path.split("/")[-1]
            return json_response(
                self,
                {
                    "skill": {
                        "skill_id": skill_id,
                        "display_name": "Workspace File Summary",
                        "status": "active",
                        "entrypoint_kind": "structured_steps",
                    },
                    "version": {
                        "version": "1.0.0",
                        "package_source": "mock",
                        "package_body": {
                            "steps_template": [
                                {"step_order": 1, "tool": "file_read"},
                                {"step_order": 2, "tool": "summarize_text"},
                            ]
                        },
                    },
                },
            )
        if path == "/tools":
            return json_response(self, [])
        if path == "/model-routes":
            return json_response(self, [])
        if path == "/model-providers":
            return json_response(self, [])
        if path == "/tasks":
            tasks = sorted(STATE.tasks.values(), key=lambda item: int(item["id"]), reverse=True)
            return json_response(self, tasks)
        if path.startswith("/tasks/"):
            parts = [part for part in path.split("/") if part]
            task_id = int(parts[1])
            task = deepcopy(STATE.tasks[task_id])
            if len(parts) == 2:
                return json_response(self, task)
            if len(parts) >= 3 and parts[2] == "steps":
                return json_response(
                    self,
                    [
                        {"id": 1, "task_id": task_id, "step_order": 1, "step_name": "分析输入", "tool_name": "mock", "status": "completed", "retry_count": 0, "max_retries": 0, "input_payload": "user_input", "output_payload": "draft complete", "error_message": ""},
                        {"id": 2, "task_id": task_id, "step_order": 2, "step_name": "检索记忆", "tool_name": "memory_search", "status": "completed", "retry_count": 0, "max_retries": 0, "input_payload": "query", "output_payload": "memory linked", "error_message": ""},
                        {"id": 3, "task_id": task_id, "step_order": 3, "step_name": "生成交付", "tool_name": "mock_answer", "status": "completed", "retry_count": 0, "max_retries": 0, "input_payload": "task", "output_payload": task["result"], "error_message": ""},
                    ],
                )
            if len(parts) >= 3 and parts[2] == "approvals":
                return json_response(self, [])
            if len(parts) >= 3 and parts[2] == "agent-runs":
                if len(parts) >= 4 and parts[3] == "summary":
                    return json_response(self, {"recommended_action": "finalize"})
                return json_response(self, [])
            if len(parts) >= 3 and parts[2] == "traces":
                return json_response(
                    self,
                    {
                        "task_id": task_id,
                        "task_trace": {"trace_id": f"task-{task_id}", "status": "completed", "plan_source": "mock"},
                        "step_traces": [],
                        "model_traces": [],
                        "tool_traces": [],
                        "skill_traces": [],
                        "retrieval_traces": [],
                    },
                )
            if len(parts) >= 3 and parts[2] == "replay":
                return json_response(
                    self,
                    {
                        "task": task,
                        "summary": {"plan_source": "mock", "step_count": 3},
                        "steps": [
                            {
                                "step_order": 1,
                                "step_name": "分析输入",
                                "status": "completed",
                                "tool_name": "mock",
                                "retry_count": 0,
                                "max_retries": 0,
                                "run_if": None,
                                "skip_if": None,
                                "input_payload": {"user_input": task["user_input"]},
                                "output_payload": "draft complete",
                                "output_data": {},
                                "replay_hints": {},
                                "trace_counts": {},
                                "approvals": [],
                            }
                        ],
                    },
                )
        if path.startswith("/agent-runs/") and path.endswith("/messages"):
            return json_response(self, [])
        if path.startswith("/agent-runs/") and path.endswith("/artifacts"):
            return json_response(self, [])
        if path == "/sessions":
            return json_response(self, [{"id": STATE.base_session_id, "summary_text": "mock session"}])
        if path.startswith("/sessions/") and path.endswith("/summary"):
            return json_response(
                self,
                {
                    "session": {"id": STATE.base_session_id},
                    "session_state": {
                        "summary_text": "mock session state",
                        "preferences": ["偏好中文总结"],
                        "open_loops": ["整理发布文档"],
                        "updated_at": utc_now(),
                    },
                    "health": {
                        "active_task_count": 1,
                        "high_importance_memory_count": 1,
                        "duplicate_memory_count": 0,
                        "open_loop_count": 1,
                        "total_reviews": 1,
                        "state_is_stale": False,
                        "daily_review_today": True,
                        "recommended_actions": [],
                    },
                },
            )
        if path.startswith("/sessions/") and path.endswith("/reviews"):
            return json_response(self, [{"id": 1, "review_kind": "manual", "summary_text": "mock review", "open_loops": [], "highlights": ["上线前先做验收"], "created_at": utc_now()}])
        if path == "/memories/search":
            query_text = (query.get("query") or [""])[0]
            return json_response(self, STATE.search_memories(query_text))
        return json_response(self, {"detail": f"Unhandled GET {path}"}, status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        content_length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(content_length) if content_length else b"{}"
        payload = json.loads(raw.decode("utf-8") or "{}")

        if path == "/intake/route":
            user_input = str(payload.get("user_input") or "").strip()
            is_fast_path = "?" in user_input or "什么" in user_input or "如何" in user_input
            route_mode = "fast_path" if is_fast_path else "draft_task"
            return json_response(
                self,
                {
                    "route_mode": route_mode,
                    "route_reason": "mock route for stable browser automation",
                    "confirmation_required": True,
                    "task_intent": {
                        "task_type": "question_answer" if is_fast_path else "research",
                        "goal_summary": user_input[:160],
                        "needs_clarification": False,
                    },
                    "deliverable_spec": {
                        "deliverable_type": "direct_answer" if is_fast_path else "research_summary",
                        "acceptance_hints": ["包含结论", "说明下一步"],
                        "clarify": {"blocking": False, "questions": []},
                    },
                    "draft_preview": {
                        "goal_summary": user_input[:160],
                        "task_type": "question_answer" if is_fast_path else "research",
                        "deliverable_type": "direct_answer" if is_fast_path else "research_summary",
                        "session_id": STATE.base_session_id,
                        "skill_id": "",
                        "needs_clarification": False,
                        "clarification_questions": [],
                        "acceptance_hints": ["包含结论", "说明下一步"],
                    },
                    "memory_context": {
                        "retrieval_query": user_input,
                        "retrieved_memories": STATE.search_memories(user_input),
                        "retrieved_count": len(STATE.search_memories(user_input)),
                    },
                },
            )
        if path == "/intake/confirm":
            user_input = str(payload.get("user_input") or "").strip()
            route = str(payload.get("route") or "draft_task")
            task = STATE.create_task(user_input=user_input, route=route)
            return json_response(self, task)
        if path.startswith("/sessions/") and path.endswith("/reviews"):
            return json_response(self, {"ok": True, "created": True})
        return json_response(self, {"detail": f"Unhandled POST {path}"}, status=404)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8000), MockApiHandler)
    server.serve_forever()
