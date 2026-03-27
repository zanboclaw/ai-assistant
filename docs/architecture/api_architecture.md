# API Architecture

当前 API 已补出 `bootstrap/ routes/ application/ domain/ infrastructure/ policy/ schemas/` 目录。

- `bootstrap/`：应用工厂、容器、环境配置。
- `routes/`：按 intake/task/session/governance/workflow/health 分域挂载。
- `application/`：草稿、任务、会话、记忆、治理与 workflow 用例封装。
- `domain/`：Task / Session / Memory / Governance / Workflow 基本对象。
- `infrastructure/`：数据库、缓存、provider、审计、工具注册适配层。
- `policy/`：权限、额度、风险策略。

## 当前已落地的主链

- `apps/api/bootstrap/app_factory.py`
  - 新 `FastAPI` 工厂已作为兼容入口，负责统一挂载 route 层。
- `apps/api/schema_runtime.py`
  - 运行时 schema 层已经收口为 contract validator；启动阶段只校验 `db/migrations/0012_runtime_schema_contract_finalize.sql` 是否落地，不再在 API 进程里执行 DDL。
- `apps/api/routes/intake_routes.py`
  - `POST /intake/route`
  - `POST /intake/confirm`
  - `POST /chat/fast-path`
  - `GET /memories/search`
  - 这些入口已不再依赖旧 `intake_task_routes.py` 暴露主链。
- `apps/api/routes/task_routes.py`
  - `POST /tasks`
  - `GET /tasks`
  - 已迁入 `application/task/create_task.py`、`application/task/list_tasks.py` 编排。
- `apps/api/schema_runtime.py`
  - 已切回 contract-only 模式：启动时只校验 runtime schema 是否满足 `db/migrations` 定义，不再在 API 进程里执行 `CREATE TABLE / ALTER TABLE`。

## 当前仍保留的兼容边界

- `apps/api/api_app_context.py`
  - 仍承载大量旧运行时能力，容器当前通过它提供兼容注入。
- `apps/api/governance_routes.py`
  - 旧治理路由仍在工作，新 `routes/governance_routes.py` 目前主要承担装配层。
- `apps/api/task_query_routes.py` / `apps/api/task_control_routes.py`
  - 任务查询与控制主链仍复用旧成熟实现，等待继续迁移到 `application/` 与 `policy/`。
