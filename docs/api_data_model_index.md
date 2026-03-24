# API 与数据模型索引

这份文档用于压缩说明当前控制面 API、关键运行对象与模块边界，方便继续拆分 `apps/api/main.py`、`apps/worker/worker.py` 时不丢上下文。

## 1. 控制面路由索引

### Intake / Fast Path / Tasks

- `POST /intake/route`
  - 文件：`apps/api/intake_task_routes.py`
  - 作用：输入分流、草稿理解、长期记忆预取。
- `POST /intake/confirm`
  - 文件：`apps/api/intake_task_routes.py`
  - 作用：按草稿确认结果创建正式任务。
- `POST /chat/fast-path`
  - 文件：`apps/api/intake_task_routes.py`
  - 作用：轻量问答接口，不进入完整任务持久化链。
- `GET /memories/search`
  - 文件：`apps/api/intake_task_routes.py`
  - 作用：按查询词检索长期记忆并返回命中解释。
- `POST /tasks`
  - 文件：`apps/api/intake_task_routes.py`
  - 作用：正式写入 `task_runs` 并 enqueue。
- `GET /tasks`
  - 文件：`apps/api/intake_task_routes.py`
  - 作用：任务列表，支持附带 stage5 summary。
- `GET /tasks/{task_id}`
  - 文件：`apps/api/main.py`
  - 作用：任务详情总览。
- `GET /tasks/{task_id}/steps`
  - 文件：`apps/api/main.py`
  - 作用：步骤列表。
- `GET /tasks/{task_id}/traces`
  - 文件：`apps/api/main.py`
  - 作用：任务、步骤、模型、工具、skill、retrieval traces。
- `GET /tasks/{task_id}/replay`
  - 文件：`apps/api/main.py`
  - 作用：只读回放 payload。
- `POST /tasks/{task_id}/interrupt`
  - 文件：`apps/api/main.py`
  - 作用：请求中断。
- `POST /tasks/{task_id}/resume`
  - 文件：`apps/api/main.py`
  - 作用：从步骤恢复。
- `POST /tasks/{task_id}/apply-recovery-action`
  - 文件：`apps/api/main.py`
  - 作用：应用自动恢复策略。
- `POST /tasks/{task_id}/clarify`
  - 文件：`apps/api/main.py`
  - 作用：补充澄清并重新规划。

### Sessions / Memory / Review

- `POST /sessions`
- `GET /sessions`
- `GET /sessions/{session_id}`
- `GET /sessions/{session_id}/summary`
- `GET /sessions/{session_id}/tasks`
- `POST /sessions/{session_id}/memories`
- `GET /sessions/{session_id}/memories`
- `GET /sessions/{session_id}/state`
- `POST /sessions/{session_id}/state/rebuild`
- `POST /sessions/{session_id}/reviews`
- `GET /sessions/{session_id}/reviews`
- `POST /reviews/daily-run`

这些路由主要仍在 `apps/api/main.py`，但其 state/review 聚合逻辑已经部分下沉到 `apps/api/session_runtime.py`。

### Governance / Monitor / Change Requests

- `GET /access/actors`
- `GET /access/quotas`
- `GET /access/quota-usage`
- `PUT /access/actors/{actor_name}`
- `PUT /access/quotas/{actor_name}`
- `GET /risk-policies`
- `PUT /risk-policies/{policy_key}`
- `GET /tools`
- `PUT /tools/{tool_name}`
- `GET /model-routes`
- `PUT /model-routes/{route_name}`
- `GET /model-providers`
- `PUT /model-providers/{provider_name}`
- `GET /monitor/overview`
- `GET /change-requests`
- `POST /change-requests`
- `POST /change-requests/{id}/approve`
- `POST /change-requests/{id}/reject`
- `POST /change-requests/{id}/apply`
- `POST /change-requests/{id}/shadow-validate`
- `GET /change-requests/{id}/shadow-validation`
- `POST /change-requests/{id}/rollback`

这些聚合与治理逻辑主要分布在：

- `apps/api/change_request_business.py`
- `apps/api/change_request_store.py`
- `apps/api/workflow_proposal_store.py`
- `apps/api/monitor_overview_store.py`
- `apps/api/monitor_stage_metrics_store.py`
- `apps/api/monitor_stage7_store.py`

## 2. 关键表与对象

### `task_runs`

- 主要字段：
  - `runtime_overrides`
  - `task_intent_json`
  - `deliverable_spec_json`
  - `validation_report_json`
  - `recovery_action_json`
  - `checkpoint_path`
  - `current_step`
- 说明：
  - 当前任务主链的核心持久化对象。
  - `fast_path` 轻量接口不再默认写入这里，只有升级为正式任务时才入库。

### `task_steps`

- 主要字段：
  - `tool_name`
  - `input_payload`
  - `output_payload`
  - `output_data`
  - `run_if`
  - `skip_if`
  - `retry_count`
  - `max_retries`
- 说明：
  - 结构化步骤执行与 replay 的主来源。

### `task_traces` / `step_traces` / `model_traces` / `tool_traces` / `skill_traces` / `retrieval_traces`

- 说明：
  - 支撑任务级可回放、可观测与后续 root-cause 分析。

### `sessions` / `session_memories` / `session_states` / `session_reviews`

- 说明：
  - 承载 working memory、review、health 与 daily review。

### `long_term_memories`

- 文件：`core/long_term_memory.py`
- 当前策略：
  - 标准化关键词
  - 命中解释 `metadata.match_explanation`
  - 匹配关键词 `metadata.matched_keywords`
  - 兜底召回说明 `metadata.citation_hint`

## 3. 关键 JSON 字段说明

### `task_runs.runtime_overrides`

- 主要子结构：
  - `skill_invocation`
  - `memory_context`
  - `intake`
  - `model_route_overrides`
  - `clarification_state`
- 说明：
  - 是任务级运行时上下文的主入口，也是后续路由拆分和 replay 组装最核心的 JSON 字段。

### `task_runs.task_intent_json`

- 作用：
  - 保存输入理解后的任务意图，如 `task_type`、`goal_summary`、`needs_clarification`。

### `task_runs.deliverable_spec_json`

- 作用：
  - 保存期望交付物类型、验收 hints、clarify questions。

### `task_runs.validation_report_json`

- 作用：
  - 保存执行结束后的验收结果、checks、摘要。

### `task_runs.recovery_action_json`

- 作用：
  - 保存失败后建议的恢复动作，如 `clarify`、`resume_task`、`replan_task`。

## 4. 模块边界索引

### API 边界

- `apps/api/main.py`
  - 保留：应用装配、重路由协调、尚未拆出的任务/审批/session 主链。
- `apps/api/intake_task_routes.py`
  - 负责：intake、memory search、task create/list、fast_path。
- `apps/api/change_request_*.py`
  - 负责：变更请求、shadow validation、rollback。
- `apps/api/session_runtime.py`
  - 负责：session health/state/review 聚合逻辑。

### Worker 边界

- `apps/worker/worker.py`
  - 保留：worker 主循环、数据库 schema bootstrap、步骤执行主线。
- `apps/worker/task_payloads.py`
  - 负责：任务 JSON 载荷读取、memory context 拼装、显示输入提取。
- `apps/worker/task_execution_runtime.py`
  - 负责：计划来源选择、structured/legacy 执行入口编排。
- `apps/worker/deliverable_runtime.py`
  - 负责：deliverable-first plan、validation、recovery action 生成。
