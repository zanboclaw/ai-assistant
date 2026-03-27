# 文档导航

更新时间：`2026-03-26`

这份文档用于说明 `docs/` 目录中哪些文档是当前有效入口，哪些属于历史归档或阶段验证材料。

## 建议阅读顺序

### 1. 先看当前项目入口

- [`README.md`](/opt/ai-assistant/README.md)
  - 适合先快速理解项目定位、能力范围、启动方式和工程化现状。

### 2. 再看运行与开发入口

- [`docs/runbook.md`](/opt/ai-assistant/docs/runbook.md)
  - 适合了解启动、初始化、Web/CLI 使用方式、核心链路和常用检查脚本。
- [`docs/api_data_model_index.md`](/opt/ai-assistant/docs/api_data_model_index.md)
  - 适合继续看 API、数据模型、模块边界和后续拆分方向。
- [`docs/architecture/system_context.md`](/opt/ai-assistant/docs/architecture/system_context.md)
  - 适合先看这轮分层重构后的系统边界、API/Worker/Web 目标结构和状态机入口。
- [`docs/adr/0002_migration_first.md`](/opt/ai-assistant/docs/adr/0002_migration_first.md)
  - 适合确认 migration-first、policy layer 和前端域拆分的关键 ADR。

### 3. 再看发布、环境与运维

- [`docs/release_runbook.md`](/opt/ai-assistant/docs/release_runbook.md)
  - 适合发布、验证、回滚。
- [`docs/environment_matrix.md`](/opt/ai-assistant/docs/environment_matrix.md)
  - 适合核对多环境配置与 secrets 注入方式。
- [`docs/operations_runbook.md`](/opt/ai-assistant/docs/operations_runbook.md)
  - 适合日常巡检、故障定位、日志落盘退化处理与值班记录。

### 4. 最后看路线与协议

- [`docs/next_execution_todo.md`](/opt/ai-assistant/docs/next_execution_todo.md)
  - 当前剩余事项与推荐执行顺序，已同步 API/Worker/前端最新模块化进展与 E2E 环境阻塞。
- [`docs/next_ai.md`](/opt/ai-assistant/docs/next_ai.md)
  - 基于当前对话上下文与本地仓库现状整理的项目后续执行文档，已同步最新真实行数、测试覆盖现状和前端拆分状态。
- [`docs/AI Assistant Platform Refactoring Complete Version Solution.md`](/opt/ai-assistant/docs/AI%20Assistant%20Platform%20Refactoring%20Complete%20Version%20Solution.md)
  - 本轮整仓重构执行依据，已开始对应落地新骨架、migration 目录、架构文档和测试分层。
- [`docs/execution_roadmap.md`](/opt/ai-assistant/docs/execution_roadmap.md)
  - 历史路线图与当前剩余主线映射。
- [`docs/frontend_experience_rebuild_plan.md`](/opt/ai-assistant/docs/frontend_experience_rebuild_plan.md)
  - 前端体验改造整体方案，适合做 Web 产品化重构和后续实施依据。
- [`docs/structured_step_protocol_v1.md`](/opt/ai-assistant/docs/structured_step_protocol_v1.md)
  - 结构化步骤协议说明。
- [`docs/multi_agent_protocol_v1.md`](/opt/ai-assistant/docs/multi_agent_protocol_v1.md)
  - 多 agent 协议说明。

## 当前有效文档

以下文档应视为当前仓库的一线文档：

- `docs/runbook.md`
- `docs/api_data_model_index.md`
- `docs/release_runbook.md`
- `docs/environment_matrix.md`
- `docs/operations_runbook.md`
- `docs/architecture/system_context.md`
- `docs/architecture/api_architecture.md`
- `docs/architecture/worker_architecture.md`
- `docs/architecture/web_architecture.md`
- `docs/adr/0001_runtime_state_machine.md`
- `docs/adr/0002_migration_first.md`
- `docs/adr/0003_policy_layer.md`
- `docs/adr/0004_frontend_domain_split.md`
- `docs/next_execution_todo.md`
- `docs/next_ai.md`
- `docs/AI Assistant Platform Refactoring Complete Version Solution.md`
- `docs/execution_roadmap.md`
- `docs/frontend_experience_rebuild_plan.md`

## 历史与辅助文档

### `docs/archive/`

- 这里主要保留历史方案、旧版规划、设计草稿和备份文档。
- 这些文档有上下文价值，但不应直接当作当前执行依据。

### `docs/validation/`

- 这里主要保留 Stage 验证清单、证据日志和阶段性收口材料。
- 它们更适合作为历史验证记录，而不是当前产品路线入口。

## 当前文档使用原则

- 代码已实现的事项，不再继续写成“待办”。
- 新增能力时，同时更新 README、runbook 和相关专题文档。
- 如果某份历史文档与当前实现冲突，以当前代码、README 和本目录的一线文档为准。
