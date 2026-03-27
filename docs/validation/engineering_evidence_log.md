# Engineering Evidence Log

这份文档用于把“本轮看起来没问题”沉淀成可追溯、可复查的工程证据。

目标不是写成长日报，而是固定三件事：

- 什么时候验证过
- 当时跑了什么
- 为什么可以判断系统仍然真实可用

建议每轮较大推进至少记录一条。

## 建议填写规则

- 一条记录对应一轮相对完整的推进或收口
- 优先记录真实执行结果，不写计划中的事项
- 如果某项没有执行，明确写“未执行”而不是留空
- 若涉及 Stage 7，必须显式记录：
  - `groundwork_completed=true/false`
  - `completed=true/false`

## 记录模板

```md
## YYYY-MM-DD HH:MM

- 目标：
- 变更范围：
- 是否代码改动：

- 已跑脚本：
  - `bash scripts/healthcheck.sh` ->
  - `bash scripts/web_console_check.sh` ->
  - 其它：

- 关键接口抽检：
  - `GET /change-requests?limit=5` ->
  - `GET /change-requests/{id}` ->
  - `GET /workflow-proposals/{id}` ->
  - `GET /workflow-proposals/{id}/shadow-validation` ->
  - `GET /tools` ->
  - `GET /model-routes` ->
  - `GET /model-providers` ->
  - `GET /monitor/overview` ->

- 数据库事务健康：
  - `pg_stat_activity` 结论：

- Stage 7 口径：
  - `groundwork_completed=`
  - `completed=`
  - 说明：

- 结论：
  - 当前是否仍然真实可用：
  - 当前是否允许继续推进：
  - 备注：
```

## 推荐记录示例

## 2026-03-22 03:53

- 目标：继续瘦身 `workflow proposal / change request` 周边编排，并保持系统可用
- 变更范围：`apps/api/main.py`、`apps/api/workflow_proposal_store.py`、`apps/api/change_request_business.py`
- 是否代码改动：是

- 已跑脚本：
  - `bash scripts/healthcheck.sh` -> 通过
  - `bash scripts/web_console_check.sh` -> `PASS=33 FAIL=0 WARN=0`
  - 其它：编译校验通过

- 关键接口抽检：
  - `GET /change-requests?limit=5` -> 正常返回
  - `GET /change-requests/420` -> 正常返回
  - `GET /workflow-proposals/985` -> 正常返回
  - `GET /workflow-proposals/985/shadow-validation` -> 正常返回
  - `GET /tools` -> 正常返回
  - `GET /model-routes` -> 正常返回
  - `GET /model-providers` -> 正常返回
  - `GET /monitor/overview` -> 正常返回

- 数据库事务健康：
  - `pg_stat_activity` 结论：仅见当前检查 SQL 为 `active`，无新的 `idle in transaction`

- Stage 7 口径：
  - `groundwork_completed=true`
  - `completed=true`
  - 说明：groundwork 已收口，且 Stage 7 overall completed 已完成升级

- 结论：
  - 当前是否仍然真实可用：是
  - 当前是否允许继续推进：是
  - 备注：读接口未出现新的锁等待或事务残留

## 2026-03-22 05:11

- 目标：在保持系统可用的前提下，加速收口 proposal / shadow validation 编排与 governance 写路由
- 变更范围：`apps/api/main.py`、`apps/api/workflow_proposal_store.py`、`apps/api/governance_helpers.py`、`apps/api/access_control.py`、`apps/api/risk_policy_helpers.py`
- 是否代码改动：是

- 已跑脚本：
  - `bash scripts/healthcheck.sh` -> 通过
  - `bash scripts/web_console_check.sh` -> `PASS=33 FAIL=0 WARN=0`
  - 其它：`python3 -m py_compile ...` 通过；`docker compose -f infra/compose/docker-compose.yml restart api` 完成

- 关键接口抽检：
  - `GET /change-requests?limit=5` -> 正常返回
  - `GET /workflow-proposals/985` -> 正常返回
  - `GET /workflow-proposals/985/shadow-validation` -> 正常返回
  - `GET /workflow-proposals/985/change-request-draft` -> 正常返回
  - `GET /tools` -> 正常返回
  - `GET /model-routes` -> 正常返回
  - `GET /model-providers` -> 正常返回
  - `GET /risk-policies` -> 正常返回
  - `GET /access/actors` -> 正常返回
  - `GET /access/quotas` -> 正常返回
  - `GET /evaluator-runs?limit=5` -> 正常返回
  - `GET /monitor/overview` -> 正常返回

- 数据库事务健康：
  - `pg_stat_activity` 结论：仅见当前检查 SQL 为 `active`，未见新的长事务或 `idle in transaction`

- Stage 7 口径：
  - `groundwork_completed=true`
  - `completed=true`
  - 说明：本轮工程侧收口、路由瘦身与既有 sandbox acceptance/rollback 能力一起支撑 Stage 7 completed 口径

- 结论：
  - 当前是否仍然真实可用：是
  - 当前是否允许继续推进：是
  - 备注：已完成 governance 写路由两轮收口，proposal / shadow validation 主链进一步下沉

## 使用建议

- 若后续改动很小，可以多轮记录合并成一条“当日汇总”
- 若本轮出现回归，应保留失败记录，不要只保留最终修复后的成功记录
- 若本轮只做文档或治理事项，也建议保留记录，以说明口径为何发生变化

## 2026-03-26 04:45

- 目标：继续按平台重构完整版方案推进 API/Worker 主链迁移，并保持兼容入口真实可用
- 变更范围：
  - `apps/api/routes/intake_routes.py`
  - `apps/api/routes/task_routes.py`
  - `apps/api/application/task/create_task.py`
  - `apps/api/application/task/list_tasks.py`
  - `apps/worker/task_processing_runtime.py`
  - `apps/worker/runtime/task_loading/load_task.py`
  - `apps/worker/runtime/planning/build_intent_plan.py`
  - `apps/worker/runtime/planning/build_execution_plan.py`
  - `apps/worker/runtime/execution/step_state_machine.py`
  - `apps/worker/runtime/execution/task_state_machine.py`
  - 对应测试与架构文档
- 是否代码改动：是

- 已跑脚本：
  - `python3 -m pytest -q tests/unit tests/integration tests/test_api_bootstrap_runtime.py tests/test_api_task_control_routes.py tests/test_worker_task_processing_runtime.py tests/test_worker_task_lifecycle_runtime.py` -> `44 passed`
  - `python3 -m compileall apps core tests scripts` -> 通过
  - `npm run check:web` -> 通过
  - 其它：
    - `python3 -m pytest -q tests/unit/api/application/test_task_application_routes.py tests/unit/api/application/test_app_factory.py tests/test_api_intake_routes.py tests/test_api_task_control_routes.py tests/integration/api/test_health_flow.py` -> 通过
    - `python3 -m pytest -q tests/test_api_routes_integration.py tests/test_api_governance_routes.py` -> 通过
    - `python3 -m pytest -q tests/test_worker_task_processing_runtime.py tests/unit/worker/planning/test_task_loading.py tests/unit/worker/planning/test_execution_plan.py tests/unit/worker/execution/test_state_machines.py tests/unit/worker/recovery/test_recovery_decider.py` -> 通过

- 关键接口抽检：
  - `GET /healthz` -> 由 `tests/integration/api/test_health_flow.py` 覆盖，正常返回
  - `GET /readyz` -> 由 `tests/integration/api/test_health_flow.py` 覆盖，正常返回
  - `GET /version` -> 由 `tests/integration/api/test_health_flow.py` 与 `tests/unit/api/application/test_app_factory.py` 覆盖，正常返回
  - `POST /intake/route` -> 新路由已由 `tests/unit/api/application/test_task_application_routes.py` 覆盖
  - `POST /intake/confirm` -> 新路由已由 `tests/unit/api/application/test_task_application_routes.py` 覆盖
  - `POST /tasks` -> 新路由已由 `tests/unit/api/application/test_task_application_routes.py` 覆盖
  - `GET /tasks` -> 新路由已由 `tests/unit/api/application/test_task_application_routes.py` 覆盖

- 数据库事务健康：
  - `pg_stat_activity` 结论：未执行，当前基于单元/集成测试与编译校验做本轮工程判断

- Stage 7 口径：
  - `groundwork_completed=false`
  - `completed=false`
  - 说明：本轮已继续推进主链迁移，但 `api_app_context.py`、`worker_runtime_context.py`、`dashboard.js` 仍未完全收口，不能宣称平台重构完成

- 结论：
  - 当前是否仍然真实可用：是
  - 当前是否允许继续推进：是
  - 备注：API 入口主链与 Worker 任务处理主链已经开始真实接入新目录，而不是只保留骨架层

## 2026-03-26 05:20

- 目标：继续按重构方案推进 Worker recovery / delivery / runtime repo 收口，并保持兼容入口与主链测试通过
- 变更范围：
  - `apps/worker/runtime/recovery/clarify_handler.py`
  - `apps/worker/runtime/recovery/recovery_actions.py`
  - `apps/worker/runtime/delivery/validate_deliverable.py`
  - `apps/worker/runtime/delivery/assemble_deliverable.py`
  - `apps/worker/infrastructure/db/runtime_repo_pg.py`
  - `apps/worker/worker_runtime_context.py`
  - 对应 unit / runtime 回归测试
- 是否代码改动：是

- 已跑脚本：
  - `python3 -m pytest -q tests/unit/worker/delivery/test_runtime_repo_pg.py tests/unit/worker/delivery/test_validate_deliverable_runtime.py tests/unit/worker/recovery/test_clarify_handler.py tests/unit/worker/recovery/test_recovery_actions.py tests/test_worker_clarification_runtime.py tests/test_worker_task_lifecycle_runtime.py tests/test_worker_task_processing_runtime.py` -> `16 passed`
  - `python3 -m compileall apps/worker tests/unit/worker tests/test_worker_clarification_runtime.py tests/test_worker_task_lifecycle_runtime.py tests/test_worker_task_processing_runtime.py` -> 通过
  - `python3 -m pytest -q tests/unit tests/integration tests/test_worker_task_processing_runtime.py tests/test_worker_task_lifecycle_runtime.py` -> `40 passed`

- 关键接口 / 主链抽检：
  - Worker `process_task` -> 由 `tests/test_worker_task_processing_runtime.py` 覆盖，正常
  - clarification failure 收口 -> 由 `tests/test_worker_clarification_runtime.py` 与 `tests/unit/worker/recovery/test_clarify_handler.py` 覆盖，正常
  - delivery validation context -> 由 `tests/unit/worker/delivery/test_validate_deliverable_runtime.py` 覆盖，正常
  - auto recovery reset -> 由 `tests/unit/worker/recovery/test_recovery_actions.py` 覆盖，正常
  - runtime repo 查询 / 写入 -> 由 `tests/unit/worker/delivery/test_runtime_repo_pg.py` 覆盖，正常

- 数据库事务健康：
  - `pg_stat_activity` 结论：未执行，当前基于运行时单测/集成回归判断本轮工程稳定性

- Stage 7 口径：
  - `groundwork_completed=false`
  - `completed=false`
  - 说明：Worker 主链继续收口，但平台整仓重构与 migration-first 仍未完成

- 结论：
  - 当前是否仍然真实可用：是
  - 当前是否允许继续推进：是
  - 备注：`worker_runtime_context.py` 仍然很大，但 recovery / delivery / repo 方向已开始真正承接历史复杂度

## 2026-03-26 05:40

- 目标：继续按 Web 重构方案推进 `composer/workspace` 域模块承接，让新前端目录不再只是占位
- 变更范围：
  - `apps/web/js/app/state.js`
  - `apps/web/js/domains/composer/*`
  - `apps/web/js/domains/workspace/*`
  - `docs/architecture/web_architecture.md`
- 是否代码改动：是

- 已跑脚本：
  - `npm run check:web` -> 通过
  - `python3 -m compileall apps/web` -> 通过

- 关键页面 / 能力抽检：
  - `composer_api` -> 已覆盖 intake / confirm / fast-path / task create / memory search 调用入口
  - `workspace_api` -> 已覆盖 task / steps / checkpoint / interrupt / resume / recovery 调用入口
  - `composer_page` / `workspace_page` -> 已注册 domain 能力到 `window.__appDomains__`

- 数据库事务健康：
  - 不适用，本轮以前端模块化与语法校验为主

- Stage 7 口径：
  - `groundwork_completed=false`
  - `completed=false`
  - 说明：前端域模块开始承接真实能力，但 `dashboard.js` 主 orchestration 仍未完全迁出

- 结论：
  - 当前是否仍然真实可用：是
  - 当前是否允许继续推进：是
  - 备注：新前端目录已开始承接真实 API/状态/页面能力，后续可继续从 legacy dashboard 中迁主逻辑

## 2026-03-26 06:15

- 目标：继续按平台重构完整版方案推进 migration-first 收口，并把 Worker 执行态仓储/投影/checkpoint 逻辑继续迁出超级文件
- 变更范围：
  - `core/long_term_memory.py`
  - `db/migrations/0010_long_term_memory_schema_finalize.sql`
  - `migrations/0002_long_term_memory.py`
  - `apps/api/intake_task_routes.py`
  - `apps/worker/infrastructure/db/task_step_repo_pg.py`
  - `apps/worker/runtime/execution/step_projection.py`
  - `apps/worker/runtime/execution/checkpoint.py`
  - `apps/worker/worker_runtime_context.py`
  - 对应单测、集成测试与测试替身
- 是否代码改动：是

- 已跑脚本：
  - `python3 -m pytest -q tests/test_api_intake_routes.py tests/test_long_term_memory.py tests/test_long_term_memory_schema.py tests/test_worker_memory_runtime.py tests/unit/worker/execution/test_task_step_repo_pg.py tests/unit/worker/execution/test_step_projection.py tests/test_worker_task_processing_runtime.py` -> `24 passed`
  - `python3 -m pytest -q tests/unit/worker/execution/test_checkpoint.py tests/unit/worker/execution/test_task_step_repo_pg.py tests/unit/worker/execution/test_step_projection.py tests/test_worker_task_lifecycle_runtime.py tests/test_worker_task_processing_runtime.py` -> `15 passed`
  - `python3 -m pytest -q tests/unit tests/integration tests/test_api_bootstrap_runtime.py tests/test_api_task_control_routes.py tests/test_worker_task_processing_runtime.py tests/test_worker_task_lifecycle_runtime.py tests/test_api_intake_routes.py tests/test_long_term_memory_schema.py` -> `66 passed`
  - `python3 -m compileall core apps/worker apps/api tests/unit/worker/execution` -> 通过

- 关键接口 / 主链抽检：
  - `POST /intake/route` -> 由 `tests/test_api_intake_routes.py` 覆盖，正常
  - `POST /intake/confirm` -> 由 `tests/test_api_intake_routes.py` 覆盖，正常
  - `POST /chat/fast-path` -> 由 `tests/test_api_intake_routes.py` 覆盖，正常
  - `GET /memories/search` -> 由 `tests/test_api_intake_routes.py` 覆盖，正常
  - Worker `process_task` -> 由 `tests/test_worker_task_processing_runtime.py` 覆盖，正常
  - Worker checkpoint / step projection / task step repo -> 由 `tests/unit/worker/execution/test_checkpoint.py`、`tests/unit/worker/execution/test_step_projection.py`、`tests/unit/worker/execution/test_task_step_repo_pg.py` 覆盖，正常

- 数据库事务健康：
  - `pg_stat_activity` 结论：未执行，本轮以回归测试、编译校验和 migration 代码审查作为工程判断依据

- Stage 7 口径：
  - `groundwork_completed=false`
  - `completed=false`
  - 说明：migration-first 与 Worker 大文件继续真实收口，但 API/Worker/Web 的旧大文件和增强链路仍未完全下线，不能宣称整份重构文档完成

- 结论：
  - 当前是否仍然真实可用：是
  - 当前是否允许继续推进：是
  - 备注：`long_term_memories` 已切回“迁移负责、运行时断言”的模式，且 Worker 执行态又有一批真实逻辑迁出 `worker_runtime_context.py`

## 2026-03-26 07:05

- 目标：继续按重构方案推进 governance schema 的 migration-first 收口，并继续拆出 Worker 工具运行时的路径安全与输入解析逻辑
- 变更范围：
  - `core/schema_migration_runtime.py`
  - `db/migrations/0011_api_governance_schema_finalize.sql`
  - `apps/api/access_control.py`
  - `apps/api/governance_helpers.py`
  - `apps/api/risk_policy_helpers.py`
  - `migrations/0003_runtime_schema_finalize.py`
  - `apps/worker/governance_runtime.py`
  - `apps/worker/runtime/tools/path_safety.py`
  - `apps/worker/runtime/tools/input_resolution.py`
  - `apps/worker/worker_runtime_context.py`
  - 对应 API/Worker schema 与工具运行时测试
- 是否代码改动：是

- 已跑脚本：
  - `python3 -m pytest -q tests/test_access_control.py tests/test_api_governance_schema_helpers.py tests/test_api_governance_routes.py tests/test_api_monitor_routes.py tests/test_api_routes_integration.py tests/test_schema_migration_runtime.py` -> `19 passed`
  - `python3 -m pytest -q tests/test_worker_governance_runtime.py tests/test_worker_approval_runtime.py tests/test_worker_tool_runtime.py tests/test_api_governance_schema_helpers.py tests/test_access_control.py` -> `30 passed`
  - `python3 -m pytest -q tests/unit/worker/tools/test_path_safety_runtime.py tests/unit/worker/tools/test_input_resolution_runtime.py tests/test_worker_local_tool_runtime.py tests/test_worker_step_request_runtime.py tests/test_worker_heuristic_planner_runtime.py tests/test_worker_task_processing_runtime.py` -> `24 passed`
  - `python3 -m pytest -q tests/unit tests/integration tests/test_api_bootstrap_runtime.py tests/test_api_task_control_routes.py tests/test_worker_task_processing_runtime.py tests/test_worker_task_lifecycle_runtime.py tests/test_api_intake_routes.py tests/test_long_term_memory_schema.py tests/test_access_control.py tests/test_api_governance_schema_helpers.py tests/test_worker_governance_runtime.py` -> `91 passed`
  - `python3 -m compileall core apps/api apps/worker migrations tests/unit/worker/tools` -> 通过

- 关键接口 / 主链抽检：
  - `GET /access/actors` / `GET /access/quota-usage` -> 由 `tests/test_api_routes_integration.py` 与 `tests/test_api_monitor_routes.py` 覆盖，正常
  - `GET /tools` / `GET /model-routes` / `GET /model-providers` / `GET /risk-policies` -> 由 `tests/test_api_governance_routes.py` 覆盖，正常
  - Worker governance settings 加载 -> 由 `tests/test_worker_governance_runtime.py` 覆盖，正常
  - Worker 本地工具 / step request / heuristic planner -> 由 `tests/test_worker_local_tool_runtime.py`、`tests/test_worker_step_request_runtime.py`、`tests/test_worker_heuristic_planner_runtime.py` 覆盖，正常

- 数据库事务健康：
  - `pg_stat_activity` 结论：未执行，本轮以 schema helper 单测、治理接口回归、Worker 主链回归和编译校验作为工程判断依据

- Stage 7 口径：
  - `groundwork_completed=false`
  - `completed=false`
  - 说明：治理 schema 与 Worker 工具运行时进一步收口，但整仓重构文档要求仍未全部完成，旧大文件与 runtime core 隐式 bootstrap 仍存在

- 结论：
  - 当前是否仍然真实可用：是
  - 当前是否允许继续推进：是
  - 备注：API/Worker 共用的治理表现在已统一转向 migration-first，`worker_runtime_context.py` 也继续按职责把工具运行时细节迁出
