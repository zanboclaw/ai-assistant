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
  - 文件：`apps/api/task_query_routes.py`
  - 作用：任务详情总览。
- `GET /tasks/{task_id}/steps`
  - 文件：`apps/api/task_query_routes.py`
  - 作用：步骤列表。
- `GET /tasks/{task_id}/traces`
  - 文件：`apps/api/task_query_routes.py`
  - 作用：任务、步骤、模型、工具、skill、retrieval traces。
- `GET /tasks/{task_id}/replay`
  - 文件：`apps/api/task_query_routes.py`
  - 作用：只读回放 payload。
- `POST /tasks/{task_id}/interrupt`
  - 文件：`apps/api/task_control_routes.py`
  - 作用：请求中断。
- `POST /tasks/{task_id}/resume`
  - 文件：`apps/api/task_control_routes.py`
  - 作用：从步骤恢复。
- `POST /tasks/{task_id}/apply-recovery-action`
  - 文件：`apps/api/task_control_routes.py`
  - 作用：应用自动恢复策略。
- `POST /tasks/{task_id}/clarify`
  - 文件：`apps/api/task_control_routes.py`
  - 作用：补充澄清并重新规划。

### Sessions / Memory / Review

- `POST /sessions`
  - 文件：`apps/api/session_routes.py`
- `GET /sessions`
  - 文件：`apps/api/session_routes.py`
- `GET /sessions/{session_id}`
  - 文件：`apps/api/session_routes.py`
- `GET /sessions/{session_id}/summary`
  - 文件：`apps/api/session_routes.py`
- `GET /sessions/{session_id}/tasks`
  - 文件：`apps/api/session_routes.py`
- `POST /sessions/{session_id}/memories`
  - 文件：`apps/api/session_routes.py`
- `GET /sessions/{session_id}/memories`
  - 文件：`apps/api/session_routes.py`
- `GET /sessions/{session_id}/state`
  - 文件：`apps/api/session_routes.py`
- `PUT /sessions/{session_id}/state`
  - 文件：`apps/api/session_routes.py`
- `POST /sessions/{session_id}/state/rebuild`
  - 文件：`apps/api/session_routes.py`
- `POST /sessions/{session_id}/reviews`
  - 文件：`apps/api/session_routes.py`
- `GET /sessions/{session_id}/reviews`
  - 文件：`apps/api/session_routes.py`
- `POST /reviews/daily-run`
  - 文件：`apps/api/session_routes.py`

这些路由已经从 `apps/api/main.py` 拆到 `apps/api/session_routes.py`，其 state/review 聚合逻辑继续由 `apps/api/session_runtime.py` 提供。

### Multi-Agent / Evaluator / Workflow Proposals

- `GET /agent-runs`
  - 文件：`apps/api/multi_agent_query_routes.py`
  - 作用：按任务、角色、状态筛选 agent run 列表。
- `GET /tasks/{task_id}/agent-runs`
  - 文件：`apps/api/multi_agent_query_routes.py`
  - 作用：查看单任务下的全部 agent run。
- `GET /tasks/{task_id}/agent-runs/summary`
  - 文件：`apps/api/multi_agent_query_routes.py`
  - 作用：聚合 manager / specialist / reviewer / evaluator 状态，给前端与监控面板提供 stage5 摘要。
- `GET /agent-runs/{agent_run_id}`
  - 文件：`apps/api/multi_agent_query_routes.py`
- `GET /agent-runs/{agent_run_id}/messages`
  - 文件：`apps/api/multi_agent_query_routes.py`
- `GET /agent-runs/{agent_run_id}/artifacts`
  - 文件：`apps/api/multi_agent_query_routes.py`
- `GET /evaluator-runs`
  - 文件：`apps/api/multi_agent_query_routes.py`
- `GET /tasks/{task_id}/evaluator-runs`
  - 文件：`apps/api/multi_agent_query_routes.py`
- `GET /tasks/{task_id}/evaluator-runs/latest`
  - 文件：`apps/api/multi_agent_query_routes.py`
- `GET /tasks/{task_id}/workflow-proposals/latest`
  - 文件：`apps/api/multi_agent_query_routes.py`
- `GET /workflow-proposals`
  - 文件：`apps/api/multi_agent_query_routes.py`
- `GET /tasks/{task_id}/workflow-proposals`
  - 文件：`apps/api/multi_agent_query_routes.py`
- `GET /workflow-proposals/{proposal_id}`
  - 文件：`apps/api/multi_agent_query_routes.py`
- `GET /workflow-proposals/{proposal_id}/shadow-validation`
  - 文件：`apps/api/multi_agent_query_routes.py`
- `GET /workflow-proposals/{proposal_id}/change-request-draft`
  - 文件：`apps/api/multi_agent_query_routes.py`
- `GET /evaluator-runs/{evaluator_run_id}`
  - 文件：`apps/api/multi_agent_query_routes.py`

这些只读查询接口已经从 `apps/api/main.py` 拆到 `apps/api/multi_agent_query_routes.py`。其中 API 侧的 stage5 summary、workflow proposal/evaluator 读取与 specialist draft helper 已收口到 `apps/api/api_multi_agent_runtime.py`，而多 agent 执行主链仍由 worker 侧的 `apps/worker/multi_agent_runtime.py` 承接。

### Multi-Agent Demo Control

- `POST /tasks/{task_id}/agent-runs/bootstrap-demo`
  - 文件：`apps/api/multi_agent_demo_routes.py`
- `POST /tasks/{task_id}/agent-runs/execute-demo`
  - 文件：`apps/api/multi_agent_demo_routes.py`
- `POST /tasks/{task_id}/agent-runs/execute-worker-demo`
  - 文件：`apps/api/multi_agent_demo_routes.py`
- `POST /tasks/{task_id}/agent-runs/finalize-demo`
  - 文件：`apps/api/multi_agent_demo_routes.py`

这些 demo 控制路由已经从 `apps/api/main.py` 拆到 `apps/api/multi_agent_demo_routes.py`。API 侧 demo 依赖的 artifact / message / run / evaluator / specialist helper 现由 `apps/api/api_multi_agent_runtime.py` 提供，worker 主线实现仍在 `apps/worker/multi_agent_runtime.py`。

### Governance / Monitor / Change Requests

- `GET /access/actors`
- `GET /audit-logs`
- `GET /runtime-metadata`
- `GET /access/quotas`
- `GET /access/quota-usage`
- `PUT /access/actors/{actor_name}`
- `PUT /access/quotas/{actor_name}`
- `GET /risk-policies`
- `PUT /risk-policies/{policy_key}`
- `GET /tools`
  - 文件：`apps/api/governance_routes.py`
- `PUT /tools/{tool_name}`
  - 文件：`apps/api/governance_routes.py`
- `GET /model-routes`
  - 文件：`apps/api/governance_routes.py`
- `PUT /model-routes/{route_name}`
  - 文件：`apps/api/governance_routes.py`
- `GET /model-providers`
  - 文件：`apps/api/governance_routes.py`
- `PUT /model-providers/{provider_name}`
  - 文件：`apps/api/governance_routes.py`
- `GET /audit-logs`
  - 文件：`apps/api/governance_routes.py`
- `GET /runtime-metadata`
  - 文件：`apps/api/governance_routes.py`
- `GET /skills`
  - 文件：`apps/api/skill_routes.py`
- `GET /skills/{skill_id}`
  - 文件：`apps/api/skill_routes.py`
- `POST /skills/import`
  - 文件：`apps/api/skill_routes.py`
- `GET /monitor/overview`
  - 文件：`apps/api/monitor_routes.py`
- `GET /change-requests`
  - 文件：`apps/api/change_request_query_routes.py`
- `GET /change-requests/{id}`
  - 文件：`apps/api/change_request_query_routes.py`
- `GET /change-requests/{id}/shadow-validation`
  - 文件：`apps/api/change_request_query_routes.py`
- `GET /change-requests/{id}/rollback-draft`
  - 文件：`apps/api/change_request_query_routes.py`
- `POST /change-requests`
  - 文件：`apps/api/change_request_control_routes.py`
- `POST /change-requests/{id}/approve`
  - 文件：`apps/api/change_request_control_routes.py`
- `POST /change-requests/{id}/reject`
  - 文件：`apps/api/change_request_control_routes.py`
- `POST /change-requests/{id}/apply`
  - 文件：`apps/api/change_request_control_routes.py`
- `POST /change-requests/{id}/shadow-validate`
  - 文件：`apps/api/change_request_control_routes.py`
- `POST /change-requests/{id}/rollback`
  - 文件：`apps/api/change_request_control_routes.py`
- `POST /workflow-proposals/{proposal_id}/change-request-draft`
  - 文件：`apps/api/change_request_control_routes.py`
- `POST /workflow-proposals/{proposal_id}/shadow-validate`
  - 文件：`apps/api/change_request_control_routes.py`

这些聚合与治理逻辑主要分布在：

- `apps/api/governance_routes.py`
- `apps/api/skill_routes.py`
- `apps/api/monitor_routes.py`
- `apps/api/change_request_query_routes.py`
- `apps/api/change_request_control_routes.py`
- `apps/api/change_request_business.py`
- `apps/api/change_request_store.py`
- `apps/api/workflow_proposal_store.py`
- `apps/api/monitor_overview_store.py`
- `apps/api/monitor_stage_metrics_store.py`
- `apps/api/monitor_stage7_store.py`

### 权限边界摘要

- `read`
  - 任务查询、session 查询、memory 检索、治理只读视图、`/monitor/overview`、`/runtime-metadata`
- `operate`
  - task `interrupt / resume / clarify / apply-recovery-action`
  - `POST /sessions`
  - session memory / review / state 的人工维护动作
  - `POST /change-requests`
  - multi-agent demo 的 bootstrap / execute / finalize
- `admin`
  - governance 直接写接口：`PUT /risk-policies/*`、`PUT /tools/*`、`PUT /model-routes/*`、`PUT /model-providers/*`
  - access actor / quota 直改
  - `POST /change-requests/{id}/approve|reject|apply`
  - `POST /skills/import`

当前这些边界都通过 `apps/api/access_control.py` 的 `require_actor_permission` 落地，相关回归已覆盖高风险治理写接口和任务控制拒绝路径。

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
  - session / actor scope 会参与排序和解释文本

### 运行版本指纹

- `GET /runtime-metadata`
- `GET /monitor/overview`
- 文件：`core/version_metadata.py`
- 当前字段：
  - `current_version`
  - `git_commit / git_short_commit`
  - `git_branch`
  - `git_dirty`
  - `build_timestamp`

用于核对容器内实际运行版本与仓库代码是否一致。

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
  - 保留：应用装配、依赖注入、路由挂载，以及 `init_db`/bootstrap 相关的极少量 shared helper。
- `apps/api/api_multi_agent_runtime.py`
  - 负责：API 侧 multi-agent helper，包括 agent artifact/message/run 写入、evaluator/workflow proposal 读取、stage5 summary 聚合、specialist step partition 与 draft payload 组装。
- `apps/api/api_shadow_validation_runtime.py`
  - 负责：workflow proposal shadow validation history/status、change request shadow validation state、completion worker/结果回写，以及 shadow validation 请求与响应装配相关的 API 上下文 helper。
- `apps/api/api_change_request_runtime.py`
  - 负责：change request 草稿创建、rollback baseline 读取、patch artifact 组装、草稿附加 patch/shadow 状态，以及 shadow validation overlay 组装。
- `apps/api/api_sandbox_runtime.py`
  - 负责：sandbox_file payload 与 acceptance 规范化、workspace/sandbox 路径约束、acceptance 执行、unified patch 应用，以及 shadow validation runtime override/monitor 辅助逻辑。
- `apps/api/api_change_apply_runtime.py`
  - 负责：change request apply/rollback 写入链，包括 sandbox/governance 目标落地、`apply_change_request_payload_with_context`、post-apply/update row 装配，以及自动 rollback change request 创建与应用。
- `apps/api/api_bootstrap_runtime.py`
  - 负责：API 入口仍保留的 bootstrap/governance 小块逻辑，包括 `init_db` 初始化流程、planner route 读取和 change gate 判断。
- `apps/api/intake_task_routes.py`
  - 负责：intake、memory search、task create/list、fast_path。
- `apps/api/task_query_routes.py`
  - 负责：task detail、steps、traces、replay、checkpoint 等只读任务查询接口。
- `apps/api/task_control_routes.py`
  - 负责：task interrupt、resume、apply recovery action、clarify、task approvals、approval 列表与 approval approve/reject。
- `apps/api/multi_agent_query_routes.py`
  - 负责：agent runs、evaluator runs、workflow proposals 的只读查询与 stage5 摘要接口。
- `apps/api/multi_agent_demo_routes.py`
  - 负责：bootstrap/execute/finalize 这组 multi-agent demo 控制路由。
- `apps/api/session_routes.py`
  - 负责：session create/list/detail、summary、health、reviews、state、memories。
- `apps/api/governance_routes.py`
  - 负责：risk policy、tool registry、model provider/route、access actor/quota、audit logs、runtime metadata。
- `apps/api/skill_routes.py`
  - 负责：skill registry 的 list/detail/import。
- `apps/api/change_request_*.py`
  - 负责：变更请求、shadow validation、rollback。
- `apps/api/change_request_query_routes.py`
  - 负责：change request list/detail、shadow validation 查询、rollback draft 预览。
- `apps/api/change_request_control_routes.py`
  - 负责：change request create/approve/reject/apply/rollback，以及 workflow proposal bridge/shadow validate。
- `apps/api/monitor_routes.py`
  - 负责：monitor overview 聚合查询与 readiness metrics 汇总。
- `apps/api/session_runtime.py`
  - 负责：session health/state/review 聚合逻辑。

### Worker 边界

- `apps/worker/worker.py`
  - 保留：worker 主循环、数据库 schema bootstrap、部分 legacy/tool helper 与步骤执行主线装配。
- `apps/worker/task_payloads.py`
  - 负责：任务 JSON 载荷读取、memory context 拼装、显示输入提取。
- `apps/worker/task_execution_runtime.py`
  - 负责：计划来源选择、structured/legacy 执行入口编排。
- `apps/worker/planner_runtime.py`
  - 负责：planner 模型调用、planner 重试、planner fallback/source 选择，以及 legacy fallback 步骤模板。
- `apps/worker/step_request_runtime.py`
  - 负责：步骤输入规范化、planner 步骤校验、执行请求富化。
- `apps/worker/approval_runtime.py`
  - 负责：step approval 查询、创建、等待审批状态写入与审批判定规则。
- `apps/worker/task_lifecycle_runtime.py`
  - 负责：任务开始、成功收口、失败收口、task runtime state 持久化、legacy step 生命周期处理。
- `apps/worker/task_processing_runtime.py`
  - 负责：`process_task` 主流程 orchestration，包括澄清阻断、规划选择、执行入口与异常分流。
- `apps/worker/structured_step_runtime.py`
  - 负责：structured step 的开始、执行请求处理、结果路由、异常收口与 step outcome/runtime state 持久化。
- `apps/worker/trace_runtime.py`
  - 负责：task/step/model/skill trace 上下文管理与 trace 写入。
- `apps/worker/memory_runtime.py`
  - 负责：任务结果摘要、memory 推断、session state rebuild、任务完成后的 memory capture。
- `apps/worker/multi_agent_runtime.py`
  - 负责：stage5/6/7 multi-agent runtime 的 artifact/message/run 写入、runtime feedback、specialist fanout strategy、execution-time fanout、postrun finalize 与 mainline agent init。
- `apps/worker/tool_runtime.py`
  - 负责：web_search/http_request/MCP tool/execute_tool 分发链、命令白名单校验与 HTTP 目标校验。
- `apps/worker/local_tool_runtime.py`
  - 负责：file/json/template/if-condition/set_var 这组本地 builtin tool 的纯逻辑实现。
- `apps/worker/governance_runtime.py`
  - 负责：risk policy、tool registry、model route/provider 的 schema/seed、缓存加载、provider client 与 route/tool 配置读取。
- `apps/worker/agent_run_runtime.py`
  - 负责：specialist agent run 的 worker 只读执行、产物写入、审计和状态收口。
- `apps/worker/queue_runtime.py`
  - 负责：task/agent queue、claim、stale requeue 与 task fetch helper。
- `apps/worker/deliverable_runtime.py`
  - 负责：deliverable-first plan、validation、recovery action 生成。

### Web 边界

- `apps/web/index.html`
  - 保留：页面骨架、多域布局、各 tab pane 容器，以及静态脚本装配入口。
- `apps/web/assets/dashboard_runtime.js`
  - 负责：API Base 解析、前端偏好与任务对话本地存储、tab 元信息等运行时配置层。
- `apps/web/assets/dashboard_task_utils.js`
  - 负责：任务状态格式化、attention/action 分类、任务搜索辅助等纯展示 helper。
- `apps/web/assets/dashboard.js`
  - 负责：当前工作台主要交互逻辑，包括任务起草器、工作区、治理、监控、Sessions 与设置页的渲染和交互。
- `apps/web/assets/dashboard.css`
  - 负责：当前整站静态样式。仍是单文件，后续如果继续推进前端模块化，可按页面域或设计 token 层继续拆分。
